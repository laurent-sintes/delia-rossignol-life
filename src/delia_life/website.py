from __future__ import annotations

import hashlib
import ipaddress
import mimetypes
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .core import load_json, sha256_file, stable_id, utc_now, write_json
from .errors import ValidationError

DEFAULT_MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        normalized_tag = tag.casefold()
        if normalized_tag in {"a", "link"} and attributes.get("href"):
            self.links.append(str(attributes["href"]))
        elif normalized_tag in {"img", "source"} and attributes.get("src"):
            self.links.append(str(attributes["src"]))


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    filtered_query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
    ]
    # ``urllib.request`` expects an ASCII request target. Decode an already
    # escaped path first so normalization is idempotent, then percent-encode
    # Unicode characters while preserving valid URL path separators.
    path = urllib.parse.quote(
        urllib.parse.unquote(parsed.path or "/"),
        safe="/:@!$&'()*+,;=-._~",
    )
    return urllib.parse.urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, urllib.parse.urlencode(sorted(filtered_query)), "")
    )


def same_origin(candidate: str, start: str) -> bool:
    left = urllib.parse.urlsplit(candidate)
    right = urllib.parse.urlsplit(start)
    return left.scheme in {"http", "https"} and left.netloc.casefold() == right.netloc.casefold()


def validate_network_url(url: str, allow_private_networks: bool = False) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError(f"Unsupported network URL: {url}")
    if allow_private_networks:
        return
    try:
        addresses = {str(item[4][0]) for item in socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        raise ValidationError(f"Cannot resolve website host {parsed.hostname}: {error}") from error
    if not addresses:
        raise ValidationError(f"Website host resolves to no address: {parsed.hostname}")
    unsafe = sorted(address for address in addresses if not ipaddress.ip_address(address).is_global)
    if unsafe:
        raise ValidationError(f"Website host resolves to a private or non-global address: {', '.join(unsafe)}")


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, start_url: str, allow_private_networks: bool) -> None:
        super().__init__()
        self.start_url = start_url
        self.allow_private_networks = allow_private_networks

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        candidate = normalize_url(urllib.parse.urljoin(req.full_url, newurl))
        if not same_origin(candidate, self.start_url):
            raise urllib.error.HTTPError(candidate, code, "Cross-origin redirect refused", headers, fp)
        validate_network_url(candidate, self.allow_private_networks)
        return super().redirect_request(req, fp, code, msg, headers, candidate)


def _robot_parser(
    start_url: str,
    user_agent: str,
    open_url: Callable[..., Any] | None = None,
) -> urllib.robotparser.RobotFileParser:
    parsed = urllib.parse.urlsplit(start_url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    parser = urllib.robotparser.RobotFileParser(robots_url)
    request = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})
    opener = open_url or urllib.request.urlopen
    try:
        with opener(request, timeout=15) as response:
            parser.parse(response.read().decode("utf-8", errors="replace").splitlines())
    except urllib.error.HTTPError as error:
        if error.code not in {401, 403, 404}:
            raise
        parser.parse(["User-agent: *", "Disallow: /" if error.code in {401, 403} else "Disallow:"])
    except (urllib.error.URLError, TimeoutError):
        parser.parse(["User-agent: *", "Disallow: /"])
    return parser


def _fetch_url(
    url: str,
    user_agent: str,
    timeout_seconds: float,
    retries: int,
    retry_delay_seconds: float,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    start_origin: str | None = None,
    open_url: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch a URL with bounded retries; callers keep the resulting error in the manifest."""
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        opener = open_url or urllib.request.urlopen
        try:
            with opener(request, timeout=timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_response_bytes:
                    return {"error": "response exceeds maximum size", "error_type": "response-too-large", "attempts": attempt + 1}
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    return {"error": "response exceeds maximum size", "error_type": "response-too-large", "attempts": attempt + 1}
                final_url = normalize_url(response.geturl())
                if start_origin and not same_origin(final_url, start_origin):
                    return {"error": "cross-origin redirect refused", "error_type": "cross-origin-redirect", "attempts": attempt + 1}
                return {
                    "media_type": response.headers.get_content_type(),
                    "charset": response.headers.get_content_charset() or "utf-8",
                    "body": body,
                    "final_url": final_url,
                    "status": response.status,
                    "attempts": attempt + 1,
                }
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == retries:
                return {"error": str(error), "attempts": attempt + 1}
            if retry_delay_seconds:
                sleep(retry_delay_seconds * (attempt + 1))
    raise AssertionError("unreachable")


def _write_progress(output_dir: Path, start_url: str, pending: deque[str], queued: set[str], visited: set[str], records: list[dict[str, Any]]) -> None:
    write_json(output_dir / "progress.json", {"start_url": start_url, "pending": list(pending), "queued": sorted(queued), "visited": sorted(visited), "records": records, "updated_at": utc_now()})


def slurp_site(
    start_url: str,
    output_dir: Path,
    max_pages: int = 50,
    delay_seconds: float = 0.5,
    user_agent: str = "DeliaCareerArchive/0.1",
    timeout_seconds: float = 30,
    retries: int = 1,
    resume: bool = True,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allow_private_networks: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    start_url = normalize_url(start_url)
    if urllib.parse.urlsplit(start_url).scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    if max_pages < 1 or max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if retries < 0 or retries > 5:
        raise ValueError("retries must be between 0 and 5")
    if max_response_bytes < 1024 or max_response_bytes > 100 * 1024 * 1024:
        raise ValueError("max_response_bytes must be between 1024 and 104857600")
    validate_network_url(start_url, allow_private_networks)

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    opener = urllib.request.build_opener(SameOriginRedirectHandler(start_url, allow_private_networks))
    robots = _robot_parser(start_url, user_agent, opener.open)
    progress_path = output_dir / "progress.json"
    if resume and progress_path.exists():
        progress = load_json(progress_path)
        if progress.get("start_url") != start_url:
            raise ValueError("Existing crawl progress belongs to another start URL")
        pending = deque(str(item) for item in progress.get("pending", []))
        queued = {str(item) for item in progress.get("queued", [])}
        visited = {str(item) for item in progress.get("visited", [])}
        records = list(progress.get("records", []))
    else:
        pending = deque([start_url])
        queued = {start_url}
        visited = set()
        records = []

    while pending and len(records) < max_pages:
        url = pending.popleft()
        if url in visited:
            continue
        visited.add(url)
        if not robots.can_fetch(user_agent, url):
            records.append({"url": url, "status": "blocked-by-robots"})
            _write_progress(output_dir, start_url, pending, queued, visited, records)
            continue

        fetched = _fetch_url(
            url,
            user_agent,
            timeout_seconds,
            retries,
            delay_seconds,
            max_response_bytes=max_response_bytes,
            start_origin=start_url,
            open_url=opener.open,
            sleep=sleep,
        )
        if "error" in fetched:
            records.append({"url": url, "status": "error", "error": fetched["error"], "error_type": fetched.get("error_type", "network"), "attempts": fetched["attempts"]})
            _write_progress(output_dir, start_url, pending, queued, visited, records)
            continue
        media_type = str(fetched["media_type"])
        body = bytes(fetched["body"])
        final_url = str(fetched["final_url"])
        status = int(fetched["status"])

        suffix = mimetypes.guess_extension(media_type) or ".bin"
        if media_type == "text/html":
            suffix = ".html"
        file_name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20] + suffix
        destination = pages_dir / file_name
        destination.write_bytes(body)
        record = {
            "url": url,
            "final_url": final_url,
            "http_status": status,
            "media_type": media_type,
            "path": destination.relative_to(output_dir).as_posix(),
            "sha256": sha256_file(destination),
            "size_bytes": len(body),
            "status": "captured",
            "attempts": fetched["attempts"],
        }
        records.append(record)

        if media_type == "text/html":
            parser = LinkParser()
            parser.feed(body.decode(str(fetched["charset"]), errors="replace"))
            for href in parser.links:
                candidate = normalize_url(urllib.parse.urljoin(final_url, href))
                if same_origin(candidate, start_url) and candidate not in queued:
                    queued.add(candidate)
                    pending.append(candidate)
        _write_progress(output_dir, start_url, pending, queued, visited, records)
        if delay_seconds:
            sleep(delay_seconds)

    manifest = {
        "id": stable_id("web", start_url, utc_now()),
        "kind": "website",
        "start_url": start_url,
        "captured_at": utc_now(),
        "max_pages": max_pages,
        "delay_seconds": delay_seconds,
        "timeout_seconds": timeout_seconds,
        "retries": retries,
        "max_response_bytes": max_response_bytes,
        "allow_private_networks": allow_private_networks,
        "user_agent": user_agent,
        "records": records,
        "truncated": bool(pending),
    }
    write_json(output_dir / "manifest.json", manifest)
    if not pending and progress_path.exists():
        progress_path.unlink()
    return manifest
