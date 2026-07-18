from __future__ import annotations

import hashlib
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .core import sha256_file, stable_id, utc_now, write_json


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


def _robot_parser(start_url: str, user_agent: str) -> urllib.robotparser.RobotFileParser:
    parsed = urllib.parse.urlsplit(start_url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    parser = urllib.robotparser.RobotFileParser(robots_url)
    request = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            parser.parse(response.read().decode("utf-8", errors="replace").splitlines())
    except urllib.error.HTTPError as error:
        if error.code not in {401, 403, 404}:
            raise
        parser.parse(["User-agent: *", "Disallow: /" if error.code in {401, 403} else "Disallow:"])
    return parser


def slurp_site(
    start_url: str,
    output_dir: Path,
    max_pages: int = 50,
    delay_seconds: float = 0.5,
    user_agent: str = "DeliaCareerArchive/0.1",
) -> dict[str, Any]:
    start_url = normalize_url(start_url)
    if urllib.parse.urlsplit(start_url).scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    if max_pages < 1 or max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    robots = _robot_parser(start_url, user_agent)
    pending: deque[str] = deque([start_url])
    queued = {start_url}
    visited: set[str] = set()
    records: list[dict[str, Any]] = []

    while pending and len(records) < max_pages:
        url = pending.popleft()
        if url in visited:
            continue
        visited.add(url)
        if not robots.can_fetch(user_agent, url):
            records.append({"url": url, "status": "blocked-by-robots"})
            continue

        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                media_type = response.headers.get_content_type()
                body = response.read()
                final_url = normalize_url(response.geturl())
                status = response.status
        except (urllib.error.URLError, TimeoutError) as error:
            records.append({"url": url, "status": "error", "error": str(error)})
            continue

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
        }
        records.append(record)

        if media_type == "text/html":
            parser = LinkParser()
            parser.feed(body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
            for href in parser.links:
                candidate = normalize_url(urllib.parse.urljoin(final_url, href))
                if same_origin(candidate, start_url) and candidate not in queued:
                    queued.add(candidate)
                    pending.append(candidate)
        if delay_seconds:
            time.sleep(delay_seconds)

    manifest = {
        "id": stable_id("web", start_url, utc_now()),
        "kind": "website",
        "start_url": start_url,
        "captured_at": utc_now(),
        "max_pages": max_pages,
        "delay_seconds": delay_seconds,
        "user_agent": user_agent,
        "records": records,
        "truncated": bool(pending),
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest
