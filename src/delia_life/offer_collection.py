from __future__ import annotations

import hashlib
import html
import http.client
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .core import load_json, stable_id, write_json
from .errors import ValidationError
from .website import (
    SameOriginRedirectHandler,
    _fetch_url,
    _robot_parser,
    normalize_url,
    validate_network_url,
)

DEFAULT_COLLECTOR_USER_AGENT = "DeliaOfferScanner/0.1"
EMPTY_RESULT_PATTERN = re.compile(
    r"\b(?:aucune\s+offre|0\s+offres?|no\s+(?:open\s+)?(?:jobs?|positions?|vacancies))\b",
    re.IGNORECASE,
)
CONTRACT_PATTERNS = (
    (re.compile(r"\bCDI\b", re.IGNORECASE), "CDI"),
    (re.compile(r"\bint[ée]rim\b", re.IGNORECASE), "intérim"),
    (re.compile(r"\bCDD\b", re.IGNORECASE), "CDD"),
    (re.compile(r"\balternance\b|\bapprentissage\b", re.IGNORECASE), "alternance"),
    (re.compile(r"\bstage\b|\binternship\b", re.IGNORECASE), "stage"),
    (re.compile(r"\bfreelance\b|\bind[ée]pendant", re.IGNORECASE), "freelance"),
)


@dataclass(frozen=True)
class CollectorSettings:
    user_agent: str = DEFAULT_COLLECTOR_USER_AGENT
    timeout_seconds: float = 30
    retries: int = 1
    delay_seconds: float = 0.5
    max_response_bytes: int = 5 * 1024 * 1024
    max_concurrent_sources: int = 6


@dataclass(frozen=True)
class OfferReference:
    url: str
    label: str


PageFetcher = Callable[[str, CollectorSettings], dict[str, Any]]
JsonPageFetcher = Callable[[str, dict[str, Any], CollectorSettings], dict[str, Any]]


class _OfferPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[tuple[str, str]] = []
        self.json_ld: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._json_ld_depth = 0
        self._json_ld_text: list[str] = []
        self.metadata: dict[str, str] = {}
        self.title_text: list[str] = []
        self.heading_text: list[str] = []
        self.page_text: list[str] = []
        self._in_title = False
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value for key, value in attrs}
        normalized = tag.casefold()
        if normalized == "a" and attributes.get("href"):
            self._anchor_href = str(attributes["href"])
            self._anchor_text = []
        if normalized == "script" and str(attributes.get("type") or "").casefold() == "application/ld+json":
            self._json_ld_depth = 1
            self._json_ld_text = []
        if normalized == "meta" and attributes.get("content"):
            key = str(attributes.get("property") or attributes.get("name") or "").casefold()
            if key:
                self.metadata[key] = str(attributes["content"])
        if normalized == "title":
            self._in_title = True
        if normalized == "h1":
            self._in_heading = True

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_text.append(data)
        if self._json_ld_depth:
            self._json_ld_text.append(data)
        if self._in_title:
            self.title_text.append(data)
        if self._in_heading:
            self.heading_text.append(data)
        self.page_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized == "a" and self._anchor_href is not None:
            label = " ".join(" ".join(self._anchor_text).split())
            self.references.append((self._anchor_href, label))
            self._anchor_href = None
            self._anchor_text = []
        if normalized == "script" and self._json_ld_depth:
            self.json_ld.append("".join(self._json_ld_text))
            self._json_ld_depth = 0
            self._json_ld_text = []
        if normalized == "title":
            self._in_title = False
        if normalized == "h1":
            self._in_heading = False


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if normalized:
            self.parts.append(normalized)


def _plain_html(value: Any) -> str:
    parser = _TextParser()
    parser.feed(html.unescape(str(value or "")))
    return " ".join(parser.parts)


def _json_ld_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _json_ld_nodes(graph)
        for key, nested in value.items():
            if key != "@graph" and isinstance(nested, (dict, list)):
                yield from _json_ld_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _json_ld_nodes(nested)


def _job_postings(parser: _OfferPageParser) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for raw in parser.json_ld:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _json_ld_nodes(document):
            node_type = node.get("@type")
            types = [node_type] if isinstance(node_type, str) else node_type if isinstance(node_type, list) else []
            if any(str(value).casefold() == "jobposting" for value in types):
                postings.append(node)
    return postings


def _organization_name(posting: dict[str, Any], fallback: str) -> str:
    organization = posting.get("hiringOrganization")
    if isinstance(organization, dict) and organization.get("name"):
        return str(organization["name"]).strip()
    return fallback


def _identifier(posting: dict[str, Any], source_url: str, title: str, employer: str) -> str:
    value = posting.get("identifier")
    if isinstance(value, dict):
        value = value.get("value") or value.get("name")
    normalized = str(value or "").strip()
    if not normalized:
        return stable_id("canonical-offer", source_url, employer, title)
    source_domain = urllib.parse.urlsplit(source_url).netloc.casefold().removeprefix("www.")
    return f"{source_domain}:{normalized}"


def _location(posting: dict[str, Any]) -> str:
    locations = posting.get("jobLocation")
    if not isinstance(locations, list):
        locations = [locations]
    labels: list[str] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if not isinstance(address, dict):
            continue
        parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]
        label = ", ".join(str(value).strip() for value in parts if value)
        if label and label not in labels:
            labels.append(label)
    return " / ".join(labels) or "Lieu non communiqué"


def _employment_values(posting: dict[str, Any]) -> list[str]:
    value = posting.get("employmentType")
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if item]


def _contract(posting: dict[str, Any], description: str) -> str:
    combined = " ".join([*_employment_values(posting), description])
    for pattern, contract in CONTRACT_PATTERNS:
        if pattern.search(combined):
            return contract
    normalized_types = {value.casefold().replace("_", "-") for value in _employment_values(posting)}
    if "part-time" in normalized_types:
        return "temps partiel"
    if "full-time" in normalized_types:
        return "temps plein - contrat non communiqué"
    return "contrat non communiqué"


def _full_time(posting: dict[str, Any], description: str) -> bool | None:
    normalized = {value.casefold().replace("_", "-") for value in _employment_values(posting)}
    plain_description = description.casefold()
    if "part-time" in normalized or "temps partiel" in plain_description:
        return False
    if "full-time" in normalized or "temps plein" in plain_description:
        return True
    return None


def _iso_date(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized[:10]).isoformat()
    except ValueError:
        return None


def _verification_status(posting: dict[str, Any], today: date) -> str:
    valid_through = _iso_date(posting.get("validThrough"))
    return "expired" if valid_through and date.fromisoformat(valid_through) < today else "active"


def _compensation(posting: dict[str, Any]) -> dict[str, Any] | None:
    salary = posting.get("baseSalary")
    if not isinstance(salary, dict):
        return None
    currency = str(salary.get("currency") or "EUR").upper()
    value = salary.get("value")
    if isinstance(value, dict):
        minimum = value.get("minValue")
        maximum = value.get("maxValue")
        unit = str(value.get("unitText") or "YEAR").casefold()
    else:
        minimum = value
        maximum = value
        unit = "year"
    if not isinstance(minimum, (int, float)) and not isinstance(maximum, (int, float)):
        return None
    periods = {"hour": "hour", "day": "hour", "month": "month", "year": "year"}
    period = next((result for marker, result in periods.items() if marker in unit), "year")
    result: dict[str, Any] = {"currency": currency, "period": period}
    if isinstance(minimum, (int, float)):
        result["minimum"] = minimum
    if isinstance(maximum, (int, float)):
        result["maximum"] = maximum
    return result


def _source_kind(source: dict[str, Any]) -> str:
    organization_type = str(source.get("organization_type") or "")
    return "specialized" if "portal" in organization_type else "direct_employer"


def _normalized_labels(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).replace("-", " ").strip() for value in values if str(value).strip()]


def _matched_query_terms(description: str, query_families: dict[str, Any]) -> list[str]:
    normalized = description.casefold()
    matches: list[str] = []
    for terms in query_families.values():
        if not isinstance(terms, list):
            continue
        for term in terms:
            text = str(term).strip()
            if text and text.casefold() in normalized and text not in matches:
                matches.append(text)
    return matches[:12]


def _job_offer(
    posting: dict[str, Any],
    page_url: str,
    source: dict[str, Any],
    query_families: dict[str, Any],
    captured_at: datetime,
) -> dict[str, Any] | None:
    title = _plain_html(posting.get("title") or posting.get("name"))
    employer = _organization_name(posting, str(source.get("organization") or "Employeur non communiqué"))
    if not title:
        return None
    description = _plain_html(posting.get("description"))
    location = _location(posting)
    posting_url = normalize_url(str(posting.get("url") or page_url))
    canonical_id = _identifier(posting, posting_url, title, employer)
    source_domain = urllib.parse.urlsplit(posting_url).netloc.casefold().removeprefix("www.")
    summary = f"Poste de {title} proposé par {employer} à {location}. Les missions et conditions détaillées figurent sur la page source vérifiée."
    evidence = [
        {"field": "title", "locator": "JSON-LD JobPosting.title", "excerpt": title[:200]},
        {"field": "employer", "locator": "JSON-LD JobPosting.hiringOrganization", "excerpt": employer[:200]},
    ]
    offer: dict[str, Any] = {
        "id": stable_id("offer", source_domain, canonical_id),
        "canonical_offer_id": canonical_id,
        "title": title,
        "employer": employer,
        "source_url": posting_url,
        "source_site": source_domain,
        "source_kind": _source_kind(source),
        "verification_status": _verification_status(posting, captured_at.date()),
        "published_at": _iso_date(posting.get("datePosted")),
        "captured_at": captured_at.isoformat(),
        "last_verified_at": captured_at.isoformat(),
        "summary": summary,
        "location_label": location,
        "industry_sector_ids": [str(value) for value in source.get("sectors", [])],
        "contract_type": _contract(posting, description),
        "full_time": _full_time(posting, description),
        "sector_labels": _normalized_labels(source.get("sectors")),
        "functional_domains": _normalized_labels(source.get("functional_domains")),
        "required_skills": _matched_query_terms(description, query_families),
        "preferred_skills": [],
        "prerequisites": [],
        "conditions": {},
        "evidence": evidence,
        "extraction": {
            "method": "deterministic-json-ld",
            "extractor_version": 1,
            "review_status": "required",
            "ambiguous_fields": ["prerequisites"] if description else ["description", "prerequisites"],
        },
    }
    compensation = _compensation(posting)
    if compensation:
        offer["compensation"] = compensation
    return offer


def _clean_page_label(parts: list[str]) -> str:
    return " ".join(html.unescape(" ".join(parts)).split())


def _location_from_text(page_text: str, policy: dict[str, Any]) -> str:
    normalized_text = _plain_search_text(page_text)
    for marker in policy.get("collector", {}).get("location_markers", []):
        normalized_marker = _plain_search_text(str(marker))
        if normalized_marker and normalized_marker in normalized_text:
            return str(marker)
    return "Lieu non communiqué"


def _html_offer(
    parser: _OfferPageParser,
    page_url: str,
    reference_label: str,
    source: dict[str, Any],
    policy: dict[str, Any],
    captured_at: datetime,
) -> dict[str, Any] | None:
    adapter = adapter_for_domain(urllib.parse.urlsplit(page_url).netloc, policy)
    if not _reference_allowed(adapter, page_url, reference_label):
        return None
    heading = _clean_page_label(parser.heading_text)
    page_title = _clean_page_label(parser.title_text).split(" | ", 1)[0].strip()
    title = heading or reference_label.strip() or page_title
    non_offer_titles = {
        "offre d'emploi",
        "nos offres",
        "emploi",
        "job",
        "candidature spontanée",
        "candidatures spontanées",
        "accéder sans concours",
    }
    if not title or _plain_search_text(title) in {_plain_search_text(value) for value in non_offer_titles}:
        return None
    title = title[:240]
    employer = str(source.get("organization") or "Employeur non communiqué")
    page_text = _clean_page_label(parser.page_text)
    location = _location_from_text(page_text, policy)
    source_domain = urllib.parse.urlsplit(page_url).netloc.casefold().removeprefix("www.")
    canonical_id = stable_id("canonical-offer", page_url)
    summary = (
        f"Poste de {title} proposé par {employer} à {location}. "
        "La page source a été archivée et doit faire l’objet d’une revue sémantique avant recommandation."
    )
    return {
        "id": stable_id("offer", source_domain, canonical_id),
        "canonical_offer_id": canonical_id,
        "title": title,
        "employer": employer,
        "source_url": page_url,
        "source_site": source_domain,
        "source_kind": _source_kind(source),
        "verification_status": "active",
        "published_at": None,
        "captured_at": captured_at.isoformat(),
        "last_verified_at": captured_at.isoformat(),
        "summary": summary,
        "location_label": location,
        "industry_sector_ids": [str(value) for value in source.get("sectors", [])],
        "contract_type": _contract({}, page_text),
        "full_time": _full_time({}, page_text),
        "sector_labels": _normalized_labels(source.get("sectors")),
        "functional_domains": _normalized_labels(source.get("functional_domains")),
        "required_skills": _matched_query_terms(page_text, policy.get("functional_query_families", {})),
        "preferred_skills": [],
        "prerequisites": [],
        "conditions": {},
        "evidence": [
            {"field": "title", "locator": "HTML h1 or listing link", "excerpt": title[:200]},
            {"field": "employer", "locator": "regional source audit", "excerpt": employer[:200]},
        ],
        "extraction": {
            "method": "deterministic-html",
            "extractor_version": 1,
            "review_status": "required",
            "ambiguous_fields": ["summary", "prerequisites", "location_label"],
        },
    }


def parse_html_offer_page(
    body: bytes,
    page_url: str,
    reference_label: str,
    source: dict[str, Any],
    policy: dict[str, Any],
    captured_at: datetime,
) -> dict[str, Any] | None:
    parser = _OfferPageParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return _html_offer(parser, page_url, reference_label, source, policy, captured_at)


def adapter_for_domain(domain: str, policy: dict[str, Any]) -> str:
    collector = policy.get("collector")
    mappings = collector.get("adapter_domains") if isinstance(collector, dict) else None
    if isinstance(mappings, dict):
        normalized = domain.casefold().removeprefix("www.")
        for adapter, domains in mappings.items():
            if isinstance(domains, list) and normalized in {str(value).casefold().removeprefix("www.") for value in domains}:
                return str(adapter)
    return "generic-html"


def _reference_allowed(adapter: str, url: str, label: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    target = f"{parsed.path} {parsed.query}".casefold()
    normalized_label = " ".join(label.casefold().split())
    generic_markers = {"emploi", "emplois", "job", "jobs", "offre", "offres", "recrutement"}
    non_offer_labels = {
        "accéder sans concours",
        "candidature spontanée",
        "candidatures spontanées",
    }
    final_path_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1].casefold()
    if normalized_label in generic_markers | non_offer_labels or (
        final_path_segment in generic_markers and not urllib.parse.parse_qs(parsed.query)
    ):
        return False
    rules = {
        "breezy": ("/p/",),
        "talentsoft": ("offre-de-emploi/emploi-", "detailoffre"),
        "softy": ("/offer/", "/offre/"),
        "workday": ("/job/",),
        "specialized": ("/offre/", "/emploi/", "offre-emploi"),
    }
    markers = rules.get(adapter)
    if markers is not None:
        return any(marker in target for marker in markers) and bool(label.strip())
    offer_path_pattern = re.compile(
        r"(?:^|[/_.?&=-])(?:emplois?|offres?|jobs?|careers?|positions?|vacanc(?:y|ies)|recrutement)"
        r"(?:$|[/_.?&=-])"
    )
    return bool(offer_path_pattern.search(target)) and bool(label.strip())


def parse_offer_page(
    body: bytes,
    page_url: str,
    source: dict[str, Any],
    policy: dict[str, Any],
    captured_at: datetime,
) -> tuple[list[dict[str, Any]], list[OfferReference]]:
    parser = _OfferPageParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    offers = [
        offer
        for posting in _job_postings(parser)
        for offer in [_job_offer(posting, page_url, source, policy.get("functional_query_families", {}), captured_at)]
        if offer is not None
    ]
    adapter = adapter_for_domain(urllib.parse.urlsplit(page_url).netloc, policy)
    references: list[OfferReference] = []
    seen: set[str] = set()
    for href, label in parser.references:
        joined = urllib.parse.urljoin(page_url, href)
        parsed_joined = urllib.parse.urlsplit(joined)
        if parsed_joined.scheme.casefold() not in {"http", "https"}:
            continue
        if parsed_joined.netloc.casefold().removeprefix("www.") != urllib.parse.urlsplit(
            page_url
        ).netloc.casefold().removeprefix("www."):
            continue
        candidate = normalize_url(joined)
        if candidate in seen or not _reference_allowed(adapter, candidate, label):
            continue
        seen.add(candidate)
        references.append(OfferReference(candidate, label))
    return offers, references


def _explicit_empty_result(body: bytes) -> bool:
    return bool(EMPTY_RESULT_PATTERN.search(_plain_html(body.decode("utf-8", errors="replace"))))


def fetch_public_page(url: str, settings: CollectorSettings) -> dict[str, Any]:
    normalized = normalize_url(url)
    try:
        validate_network_url(normalized)
        opener = urllib.request.build_opener(SameOriginRedirectHandler(normalized, False))
        robots = _robot_parser(normalized, settings.user_agent, opener.open)
    except (
        ValidationError,
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        http.client.HTTPException,
    ) as error:
        return {"capture_status": "network-error", "url": normalized, "error": str(error)}
    if not robots.can_fetch(settings.user_agent, normalized):
        return {"capture_status": "blocked-by-robots", "url": normalized}
    fetched = _fetch_url(
        normalized,
        settings.user_agent,
        settings.timeout_seconds,
        settings.retries,
        settings.delay_seconds,
        max_response_bytes=settings.max_response_bytes,
        start_origin=normalized,
        open_url=opener.open,
    )
    if "error" in fetched:
        return {"capture_status": "error", "url": normalized, **fetched}
    return {"capture_status": "captured", "url": normalized, **fetched}


def fetch_public_json_post(
    url: str,
    payload: dict[str, Any],
    settings: CollectorSettings,
) -> dict[str, Any]:
    normalized = normalize_url(url)
    try:
        validate_network_url(normalized)
        opener = urllib.request.build_opener(SameOriginRedirectHandler(normalized, False))
        robots = _robot_parser(normalized, settings.user_agent, opener.open)
    except (
        ValidationError,
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        http.client.HTTPException,
    ) as error:
        return {"capture_status": "network-error", "url": normalized, "error": str(error)}
    if not robots.can_fetch(settings.user_agent, normalized):
        return {"capture_status": "blocked-by-robots", "url": normalized}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    for attempt in range(settings.retries + 1):
        request = urllib.request.Request(
            normalized,
            data=body,
            headers={"User-Agent": settings.user_agent, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(request, timeout=settings.timeout_seconds) as response:
                content = response.read(settings.max_response_bytes + 1)
                if len(content) > settings.max_response_bytes:
                    return {"capture_status": "error", "url": normalized, "error": "response exceeds maximum size"}
                return {
                    "capture_status": "captured",
                    "url": normalized,
                    "final_url": normalize_url(response.geturl()),
                    "status": response.status,
                    "media_type": response.headers.get_content_type(),
                    "body": content,
                    "attempts": attempt + 1,
                }
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.HTTPException,
        ) as error:
            if attempt == settings.retries:
                return {"capture_status": "error", "url": normalized, "error": str(error)}
            if settings.delay_seconds:
                time.sleep(settings.delay_seconds * (attempt + 1))
    raise AssertionError("unreachable")


def _plain_search_text(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").casefold()


def _offer_within_search_area(offer: dict[str, Any], policy: dict[str, Any]) -> bool:
    if str(offer.get("source_site") or "") == "ars-nouvelle-aquitaine-recrute.talent-soft.com":
        department_match = re.search(r"\bDD(\d{2})\b", str(offer.get("title") or ""), re.IGNORECASE)
        if department_match is not None and department_match.group(1) != "33":
            return False
    location = " ".join(_plain_search_text(str(offer.get("location_label") or "")).split())
    if not location or location in {"lieu non communique", "non communique"}:
        return True
    markers = [
        " ".join(_plain_search_text(str(value)).split())
        for value in policy.get("collector", {}).get("location_markers", [])
    ]
    return not markers or any(marker in location for marker in markers)


def _workday_references(
    start_url: str,
    policy: dict[str, Any],
    settings: CollectorSettings,
    fetch_json: JsonPageFetcher,
    archive_directory: Path,
) -> tuple[list[OfferReference], list[dict[str, Any]], str | None]:
    parsed = urllib.parse.urlsplit(start_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        return [], [], "Workday URL does not declare locale and site id"
    tenant = parsed.netloc.split(".", 1)[0]
    site_id = path_parts[1]
    endpoint = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, f"/wday/cxs/{tenant}/{site_id}/jobs", "", "")
    )
    markers = [
        _plain_search_text(str(value))
        for value in policy.get("collector", {}).get("location_markers", [])
    ]
    references: list[OfferReference] = []
    records: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        fetched = fetch_json(
            endpoint,
            {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
            settings,
        )
        if fetched.get("capture_status") != "captured":
            return references, records, str(fetched.get("error") or fetched.get("capture_status") or "Workday API error")
        records.append(_archive_page(archive_directory, f"{endpoint}?offset={offset}", fetched))
        try:
            document = json.loads(bytes(fetched["body"]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return references, records, f"invalid Workday JSON: {error}"
        total = int(document.get("total", 0))
        postings = document.get("jobPostings", [])
        if not isinstance(postings, list) or not postings:
            break
        for posting in postings:
            if not isinstance(posting, dict):
                continue
            location = _plain_search_text(str(posting.get("locationsText") or ""))
            if markers and not any(marker in location for marker in markers):
                continue
            external_path = str(posting.get("externalPath") or "")
            title = str(posting.get("title") or "").strip()
            if external_path and title:
                detail_url = f"{start_url.rstrip('/')}/{external_path.lstrip('/')}"
                references.append(OfferReference(normalize_url(detail_url), title))
        offset += len(postings)
    return references, records, None


def _decode_document_write(body: bytes) -> bytes | None:
    text = body.decode("utf-8", errors="replace").strip()
    match = re.fullmatch(r"document\.write\('(.*)'\)\s*", text, re.DOTALL)
    if match is None:
        return None
    decoded = (
        match.group(1)
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\'", "'")
        .replace("\\\\", "\\")
    )
    return decoded.encode("utf-8")


def _jobaffinity_offers(
    start_url: str,
    landing_body: bytes,
    source: dict[str, Any],
    policy: dict[str, Any],
    settings: CollectorSettings,
    fetch_page: PageFetcher,
    archive_directory: Path,
    captured_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    publication_match = re.search(
        r"https://jobaffinity\.fr/syndication/publication/(\d+)/(\d+)",
        landing_body.decode("utf-8", errors="replace"),
    )
    if publication_match is None:
        return [], [], "page source sans identifiant de publication JobAffinity"
    account_id, source_id = publication_match.groups()
    parent = urllib.parse.quote(start_url, safe="")
    list_url = f"https://jobaffinity.fr/syndication/list_job/{account_id}/{source_id}/?parent={parent}"
    fetched_list = fetch_page(list_url, settings)
    if fetched_list.get("capture_status") != "captured":
        return [], [], str(fetched_list.get("error") or fetched_list.get("capture_status"))
    records = [_archive_page(archive_directory, list_url, fetched_list)]
    list_html = _decode_document_write(bytes(fetched_list["body"]))
    if list_html is None:
        return [], records, "réponse JobAffinity liste illisible"
    parser = _OfferPageParser()
    parser.feed(list_html.decode("utf-8", errors="replace"))
    references: list[OfferReference] = []
    for href, label in parser.references:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        intuition_ids = query.get("intuition_id", [])
        if not intuition_ids or "candidature spontan" in _plain_search_text(label):
            continue
        references.append(OfferReference(normalize_url(href), label.strip()))

    offers: list[dict[str, Any]] = []
    failures: list[str] = []
    for reference in references:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(reference.url).query)
        intuition_id = query["intuition_id"][0]
        detail_url = (
            f"https://jobaffinity.fr/syndication/info_job/{account_id}/{source_id}/{intuition_id}"
            f"?parent={urllib.parse.quote(reference.url, safe='')}"
        )
        fetched_detail = fetch_page(detail_url, settings)
        if fetched_detail.get("capture_status") != "captured":
            failures.append(f"{intuition_id}: {fetched_detail.get('error') or fetched_detail.get('capture_status')}")
            continue
        record = _archive_page(archive_directory, detail_url, fetched_detail)
        records.append(record)
        detail_html = _decode_document_write(bytes(fetched_detail["body"]))
        if detail_html is None:
            failures.append(f"{intuition_id}: réponse détail illisible")
            continue
        offer = parse_html_offer_page(
            detail_html,
            reference.url,
            reference.label,
            source,
            policy,
            captured_at,
        )
        if offer is None:
            failures.append(f"{intuition_id}: annonce non extraite")
            continue
        _attach_capture_metadata([offer], record)
        offers.append(offer)
    error = f"{len(failures)} fiche(s) JobAffinity non extraite(s)" if failures else None
    return offers, records, error


def _bpce_offers(
    start_url: str,
    source: dict[str, Any],
    policy: dict[str, Any],
    settings: CollectorSettings,
    fetch_json: JsonPageFetcher,
    archive_directory: Path,
    captured_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    parsed = urllib.parse.urlsplit(start_url)
    endpoint = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/app/wp-json/bpce/v1/search/jobs", "", "")
    )
    markers = [
        _plain_search_text(str(value))
        for value in policy.get("collector", {}).get("location_markers", [])
    ]
    records: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        fetched = fetch_json(
            endpoint,
            {"lang": "fr", "tax_department": "gironde", "size": "50", "from": str(offset)},
            settings,
        )
        if fetched.get("capture_status") != "captured":
            return offers, records, str(fetched.get("error") or fetched.get("capture_status") or "BPCE API error")
        api_record = _archive_page(archive_directory, f"{endpoint}?from={offset}", fetched)
        records.append(api_record)
        try:
            document = json.loads(bytes(fetched["body"]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return offers, records, f"invalid BPCE JSON: {error}"
        data = document.get("data") if isinstance(document, dict) else None
        if not isinstance(data, dict):
            return offers, records, "BPCE API response has no data object"
        total = int(data.get("total", 0))
        items = data.get("items", [])
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            location = str(item.get("localisation") or "")
            normalized_location = _plain_search_text(location)
            if markers and not any(marker in normalized_location for marker in markers):
                continue
            title = _plain_html(item.get("title"))
            if not title or "candidature spontan" in _plain_search_text(title):
                continue
            reference = str(item.get("job_number") or item.get("advert_id") or item.get("post_id") or "")
            link_value = item.get("link")
            link: dict[str, Any] = link_value if isinstance(link_value, dict) else {}
            offer_url = normalize_url(urllib.parse.urljoin(start_url, str(link.get("url") or f"/job/{reference}")))
            description = _plain_html(item.get("description"))
            brands = item.get("brand") if isinstance(item.get("brand"), list) else []
            employer = str(brands[0]) if brands else str(source.get("organization") or "Groupe BPCE")
            contracts = item.get("contract") if isinstance(item.get("contract"), list) else []
            contract = str(contracts[0]) if contracts else _contract({}, description)
            canonical_id = f"{parsed.netloc.casefold()}:{reference}" if reference else stable_id("canonical-offer", offer_url)
            offer = {
                    "id": stable_id("offer", parsed.netloc.casefold(), canonical_id),
                    "canonical_offer_id": canonical_id,
                    "title": title,
                    "employer": employer,
                    "source_url": offer_url,
                    "source_site": parsed.netloc.casefold().removeprefix("www."),
                    "source_kind": _source_kind(source),
                    "verification_status": "active",
                    "published_at": _iso_date(item.get("date")),
                    "captured_at": captured_at.isoformat(),
                    "last_verified_at": captured_at.isoformat(),
                    "summary": f"Poste de {title} proposé par {employer} à {location or 'un lieu non communiqué'}. Revue sémantique requise avant recommandation.",
                    "location_label": location or "Lieu non communiqué",
                    "industry_sector_ids": [str(value) for value in source.get("sectors", [])],
                    "contract_type": contract,
                    "full_time": _full_time({}, description),
                    "sector_labels": _normalized_labels(source.get("sectors")),
                    "functional_domains": _normalized_labels(source.get("functional_domains")),
                    "required_skills": _matched_query_terms(description, policy.get("functional_query_families", {})),
                    "preferred_skills": [],
                    "prerequisites": [],
                    "conditions": {},
                    "evidence": [
                        {"field": "title", "locator": "BPCE API item.title", "excerpt": title[:200]},
                        {"field": "location_label", "locator": "BPCE API item.localisation", "excerpt": (location or "non communiqué")[:200]},
                    ],
                    "extraction": {
                        "method": "deterministic-api",
                        "extractor_version": 1,
                        "review_status": "required",
                        "ambiguous_fields": ["summary", "prerequisites"],
                    },
                }
            _attach_capture_metadata([offer], api_record)
            offers.append(offer)
        offset += len(items)
    return offers, records, None


def _collector_settings(policy: dict[str, Any]) -> CollectorSettings:
    value = policy.get("collector")
    collector = value if isinstance(value, dict) else {}
    return CollectorSettings(
        user_agent=str(collector.get("user_agent") or DEFAULT_COLLECTOR_USER_AGENT),
        timeout_seconds=float(collector.get("timeout_seconds", 30)),
        retries=int(collector.get("retries", 1)),
        delay_seconds=float(collector.get("delay_seconds", 0.5)),
        max_response_bytes=int(collector.get("max_response_bytes", 5 * 1024 * 1024)),
        max_concurrent_sources=int(collector.get("max_concurrent_sources", 6)),
    )


def _archive_page(archive_directory: Path, url: str, fetched: dict[str, Any]) -> dict[str, Any]:
    body = bytes(fetched["body"])
    digest = hashlib.sha256(body).hexdigest()
    media_type = str(fetched.get("media_type") or "application/octet-stream")
    suffix = ".html" if media_type == "text/html" else ".bin"
    destination = archive_directory / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return {
        "url": url,
        "final_url": fetched.get("final_url", url),
        "http_status": fetched.get("status"),
        "media_type": media_type,
        "sha256": digest,
        "size_bytes": len(body),
        "archive_path": destination.as_posix(),
    }


def _source_by_domain(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source in audit.get("sources", []):
        if not isinstance(source, dict):
            continue
        domain = str(source.get("scan_domain") or "").casefold().removeprefix("www.")
        if domain:
            result[domain] = source
    return result


def _write_collected_offers(offers: dict[str, dict[str, Any]], output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for offer in offers.values():
        write_json(output_directory / f"{offer['id']}.json", offer)


def _attach_capture_metadata(offers: list[dict[str, Any]], record: dict[str, Any]) -> None:
    for offer in offers:
        extraction = offer.get("extraction")
        if isinstance(extraction, dict):
            extraction.setdefault("source_archive_path", record["archive_path"])
            extraction.setdefault("source_sha256", record["sha256"])


def _collect_source(
    domain: str,
    source: dict[str, Any] | None,
    policy: dict[str, Any],
    required: dict[str, Any],
    archive_directory: Path,
    settings: CollectorSettings,
    fetch_page: PageFetcher,
    fetch_json: JsonPageFetcher,
    effective_now: datetime,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if source is None:
        return (
            {"domain": domain, "status": "configuration-error", "error": "source absent from regional audit"},
            {},
        )
    start_url = str(source.get("career_url") or "")
    receipt: dict[str, Any] = {
        "domain": domain,
        "organization": source.get("organization"),
        "adapter": adapter_for_domain(domain, policy),
        "start_url": start_url,
        "attempted_at": effective_now.isoformat(),
        "pages_fetched": 0,
        "offers_discovered": 0,
        "offers_extracted": 0,
        "detail_failures": 0,
        "detail_warnings": 0,
        "outside_area": 0,
        "records": [],
    }
    local_collected: dict[str, dict[str, Any]] = {}
    fetched = fetch_page(start_url, settings)
    if fetched.get("capture_status") != "captured":
        receipt.update({"status": fetched.get("capture_status", "error"), "error": fetched.get("error")})
        return receipt, local_collected
    archived = _archive_page(archive_directory / domain, start_url, fetched)
    receipt["records"].append(archived)
    receipt["pages_fetched"] = 1
    landing_offers, references = parse_offer_page(
        bytes(fetched["body"]),
        str(fetched.get("final_url") or start_url),
        source,
        policy,
        effective_now,
    )
    explicit_empty = _explicit_empty_result(bytes(fetched["body"]))
    if receipt["adapter"] == "workday" and not references:
        workday_references, workday_records, workday_error = _workday_references(
            start_url,
            policy,
            settings,
            fetch_json,
            archive_directory / domain,
        )
        receipt["records"].extend(workday_records)
        receipt["pages_fetched"] = int(receipt["pages_fetched"]) + len(workday_records)
        if workday_error:
            receipt.update({"status": "partial", "error": workday_error})
            return receipt, local_collected
        references = workday_references
        explicit_empty = not references
    if receipt["adapter"] == "jobaffinity" and not references and not landing_offers:
        jobaffinity_offers, jobaffinity_records, jobaffinity_error = _jobaffinity_offers(
            start_url,
            bytes(fetched["body"]),
            source,
            policy,
            settings,
            fetch_page,
            archive_directory / domain,
            effective_now,
        )
        receipt["records"].extend(jobaffinity_records)
        receipt["pages_fetched"] = int(receipt["pages_fetched"]) + len(jobaffinity_records)
        if jobaffinity_error:
            receipt.update({"status": "partial", "error": jobaffinity_error})
            return receipt, local_collected
        landing_offers = jobaffinity_offers
        explicit_empty = not landing_offers
    if receipt["adapter"] == "bpce" and not references and not landing_offers:
        bpce_offers, bpce_records, bpce_error = _bpce_offers(
            start_url,
            source,
            policy,
            settings,
            fetch_json,
            archive_directory / domain,
            effective_now,
        )
        receipt["records"].extend(bpce_records)
        receipt["pages_fetched"] = int(receipt["pages_fetched"]) + len(bpce_records)
        if bpce_error:
            receipt.update({"status": "partial", "error": bpce_error})
            return receipt, local_collected
        landing_offers = bpce_offers
        explicit_empty = not landing_offers
    _attach_capture_metadata(landing_offers, archived)
    inside_area_landing = [offer for offer in landing_offers if _offer_within_search_area(offer, policy)]
    receipt["outside_area"] = int(receipt["outside_area"]) + len(landing_offers) - len(inside_area_landing)
    landing_offers = inside_area_landing
    receipt["offers_discovered"] = len(references) + len(landing_offers)
    if not landing_offers and not references and not explicit_empty:
        receipt.update(
            {
                "status": "unverified-empty",
                "error": "page reached but adapter found neither offers nor an explicit empty-result marker",
            }
        )
        return receipt, local_collected
    for offer in landing_offers:
        local_collected[str(offer["canonical_offer_id"])] = offer

    for reference in references:
        detailed = fetch_page(reference.url, settings)
        if detailed.get("capture_status") != "captured":
            error_message = str(detailed.get("error") or "")
            if "HTTP Error 404" in error_message or "HTTP Error 410" in error_message:
                receipt["detail_warnings"] = int(receipt["detail_warnings"]) + 1
                receipt["records"].append(
                    {"url": reference.url, "status": "closed", "error": error_message}
                )
                continue
            receipt["detail_failures"] = int(receipt["detail_failures"]) + 1
            receipt["records"].append(
                {
                    "url": reference.url,
                    "status": detailed.get("capture_status", "error"),
                    "error": detailed.get("error"),
                }
            )
            continue
        record = _archive_page(archive_directory / domain, reference.url, detailed)
        receipt["records"].append(record)
        receipt["pages_fetched"] = int(receipt["pages_fetched"]) + 1
        detailed_offers, _ = parse_offer_page(
            bytes(detailed["body"]),
            str(detailed.get("final_url") or reference.url),
            source,
            policy,
            effective_now,
        )
        if not detailed_offers:
            html_offer = parse_html_offer_page(
                bytes(detailed["body"]),
                str(detailed.get("final_url") or reference.url),
                reference.label,
                source,
                policy,
                effective_now,
            )
            detailed_offers = [html_offer] if html_offer is not None else []
        extraction_succeeded = bool(detailed_offers)
        _attach_capture_metadata(detailed_offers, record)
        inside_area_details = [offer for offer in detailed_offers if _offer_within_search_area(offer, policy)]
        receipt["outside_area"] = int(receipt["outside_area"]) + len(detailed_offers) - len(inside_area_details)
        detailed_offers = inside_area_details
        if not extraction_succeeded:
            receipt["detail_warnings"] = int(receipt["detail_warnings"]) + 1
            record["extraction_status"] = "rejected-non-offer-page"
        for offer in detailed_offers:
            local_collected[str(offer["canonical_offer_id"])] = offer
        if settings.delay_seconds:
            time.sleep(settings.delay_seconds)

    receipt["offers_extracted"] = len(local_collected)
    receipt["status"] = "partial" if receipt["detail_failures"] else "success"
    if receipt["detail_failures"]:
        receipt["error"] = f"{receipt['detail_failures']} discovered offer page(s) could not be extracted"
    receipt["query_families"] = sorted(str(value) for value in source.get("functional_domains", []))
    receipt["priority_sectors"] = sorted(
        set(str(value) for value in source.get("sectors", []))
        & set(str(value) for value in required.get("required_priority_sectors", []))
    )
    return receipt, local_collected


def collect_offers(
    manifest_path: Path,
    *,
    policy_path: Path = Path("config/offer-search.json"),
    source_audit_path: Path | None = None,
    archive_root: Path = Path("private/offer-scan-archives"),
    fetch_page: PageFetcher = fetch_public_page,
    fetch_json: JsonPageFetcher = fetch_public_json_post,
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or not manifest.get("scan_id"):
        raise ValueError("invalid offer scan manifest")
    if manifest.get("collection") is not None:
        raise ValueError("offer scan manifest has already been collected; prepare a new scan")
    policy = load_json(policy_path)
    audit_path = source_audit_path or Path(str(policy["regional_source_audit"]))
    audit = load_json(audit_path)
    settings = _collector_settings(policy)
    effective_now = now or datetime.now().astimezone()
    if effective_now.tzinfo is None:
        raise ValueError("offer collection time must include a timezone")
    requirements_value = manifest.get("requirements")
    required: dict[str, Any] = requirements_value if isinstance(requirements_value, dict) else {}
    required_domains = [str(value) for value in required.get("required_source_domains", [])]
    sources = _source_by_domain(audit)
    output_directory = Path(str(manifest["offer_output_directory"]))
    archive_directory = archive_root / str(manifest["scan_id"])
    receipts: list[dict[str, Any]] = []
    collected: dict[str, dict[str, Any]] = {}
    visited_sources: list[str] = []
    covered_queries: set[str] = set()
    covered_sectors: set[str] = set()

    with ThreadPoolExecutor(max_workers=settings.max_concurrent_sources) as executor:
        futures = {
            domain: executor.submit(
                _collect_source,
                domain,
                sources.get(domain),
                policy,
                required,
                archive_directory,
                settings,
                fetch_page,
                fetch_json,
                effective_now,
            )
            for domain in required_domains
        }
        results = {domain: futures[domain].result() for domain in required_domains}

    for domain in required_domains:
        receipt, source_offers = results[domain]
        collected.update(source_offers)
        if receipt.get("status") == "success":
            visited_sources.append(str(receipt["start_url"]))
            covered_queries.update(receipt.get("query_families", []))
            covered_sectors.update(receipt.get("priority_sectors", []))
        receipts.append(receipt)

    failed_domains = sorted(str(item["domain"]) for item in receipts if item.get("status") != "success")
    missing_query_families = sorted(
        set(str(value) for value in required.get("required_query_families", [])) - covered_queries
    )
    missing_priority_sectors = sorted(
        set(str(value) for value in required.get("required_priority_sectors", [])) - covered_sectors
    )
    collection_complete = not failed_domains and not missing_query_families and not missing_priority_sectors
    collected_output_directory = output_directory if collection_complete else archive_directory / "partial-offers"
    _write_collected_offers(collected, collected_output_directory)
    semantic_review_queue = [
        {
            "offer_id": offer["id"],
            "offer_path": str(collected_output_directory / f"{offer['id']}.json"),
            "source_url": offer["source_url"],
            "source_archive_path": offer.get("extraction", {}).get("source_archive_path"),
            "ambiguous_fields": offer.get("extraction", {}).get("ambiguous_fields", []),
        }
        for offer in collected.values()
        if offer.get("extraction", {}).get("review_status") == "required"
    ]
    collection = {
        "schema_version": 2,
        "collected_at": effective_now.isoformat(),
        "archive_directory": str(archive_directory),
        "source_receipts": receipts,
        "visited_sources": visited_sources,
        "covered_query_families": sorted(covered_queries),
        "covered_priority_sectors": sorted(covered_sectors),
        "manual_source_domains": sorted(
            str(value) for value in required.get("manual_source_domains", [])
        ),
        "failed_source_domains": failed_domains,
        "missing_query_families": missing_query_families,
        "missing_priority_sectors": missing_priority_sectors,
        "offer_count": len(collected),
        "semantic_review_queue": semantic_review_queue,
        "semantic_review_required_count": len(semantic_review_queue),
        "collected_output_directory": str(collected_output_directory),
        "promoted_to_rank_inputs": collection_complete,
        "complete": collection_complete,
    }
    updated_manifest: dict[str, Any] = {
        **manifest,
        "schema_version": 2,
        "collection": collection,
        "status": "collected" if collection["complete"] else "collection-incomplete",
    }
    write_json(manifest_path, updated_manifest)
    write_json(archive_directory / "manifest.json", collection)
    return collection
