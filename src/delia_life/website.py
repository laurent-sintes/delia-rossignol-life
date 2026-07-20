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
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .core import load_json, sha256_file, stable_id, utc_now, write_json
from .errors import ValidationError

DEFAULT_MAX_RESPONSE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class CrawlConfig:
    start_url: str
    output_dir: Path
    max_pages: int = 50
    delay_seconds: float = 0.5
    user_agent: str = "DeliaCareerArchive/0.1"
    timeout_seconds: float = 30
    retries: int = 1
    resume: bool = True
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    allow_private_networks: bool = False
    sleep: Callable[[float], None] = time.sleep


@dataclass
class CrawlState:
    pending: deque[str]
    queued: set[str]
    visited: set[str]
    records: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CrawlRuntime:
    config: CrawlConfig
    state: CrawlState
    pages_dir: Path
    opener: Any
    robots: urllib.robotparser.RobotFileParser


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


def _validate_crawl_config(config: CrawlConfig) -> None:
    if urllib.parse.urlsplit(config.start_url).scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    if config.max_pages < 1 or config.max_pages > 500:
        raise ValueError("max_pages must be between 1 and 500")
    if config.delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")
    if config.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if config.retries < 0 or config.retries > 5:
        raise ValueError("retries must be between 0 and 5")
    if config.max_response_bytes < 1024 or config.max_response_bytes > 100 * 1024 * 1024:
        raise ValueError("max_response_bytes must be between 1024 and 104857600")
    validate_network_url(config.start_url, config.allow_private_networks)


def _load_crawl_state(config: CrawlConfig) -> CrawlState:
    progress_path = config.output_dir / "progress.json"
    if config.resume and progress_path.exists():
        progress = load_json(progress_path)
        if progress.get("start_url") != config.start_url:
            raise ValueError("Existing crawl progress belongs to another start URL")
        return CrawlState(
            pending=deque(str(item) for item in progress.get("pending", [])),
            queued={str(item) for item in progress.get("queued", [])},
            visited={str(item) for item in progress.get("visited", [])},
            records=list(progress.get("records", [])),
        )
    return CrawlState(pending=deque([config.start_url]), queued={config.start_url}, visited=set())


def _write_progress(config: CrawlConfig, state: CrawlState) -> None:
    write_json(
        config.output_dir / "progress.json",
        {
            "start_url": config.start_url,
            "pending": list(state.pending),
            "queued": sorted(state.queued),
            "visited": sorted(state.visited),
            "records": state.records,
            "updated_at": utc_now(),
        },
    )


def _captured_record(runtime: CrawlRuntime, url: str, fetched: dict[str, Any]) -> dict[str, Any]:
    media_type = str(fetched["media_type"])
    body = bytes(fetched["body"])
    suffix = ".html" if media_type == "text/html" else mimetypes.guess_extension(media_type) or ".bin"
    destination = runtime.pages_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:20] + suffix)
    destination.write_bytes(body)
    return {
        "url": url,
        "final_url": str(fetched["final_url"]),
        "http_status": int(fetched["status"]),
        "media_type": media_type,
        "path": destination.relative_to(runtime.config.output_dir).as_posix(),
        "sha256": sha256_file(destination),
        "size_bytes": len(body),
        "status": "captured",
        "attempts": fetched["attempts"],
    }


def _enqueue_page_links(runtime: CrawlRuntime, fetched: dict[str, Any]) -> None:
    if str(fetched["media_type"]) != "text/html":
        return
    parser = LinkParser()
    parser.feed(bytes(fetched["body"]).decode(str(fetched["charset"]), errors="replace"))
    final_url = str(fetched["final_url"])
    for href in parser.links:
        candidate = normalize_url(urllib.parse.urljoin(final_url, href))
        if same_origin(candidate, runtime.config.start_url) and candidate not in runtime.state.queued:
            runtime.state.queued.add(candidate)
            runtime.state.pending.append(candidate)


def _process_crawl_url(runtime: CrawlRuntime, url: str) -> None:
    config = runtime.config
    state = runtime.state
    if not runtime.robots.can_fetch(config.user_agent, url):
        state.records.append({"url": url, "status": "blocked-by-robots"})
        _write_progress(config, state)
        return
    fetched = _fetch_url(
        url,
        config.user_agent,
        config.timeout_seconds,
        config.retries,
        config.delay_seconds,
        max_response_bytes=config.max_response_bytes,
        start_origin=config.start_url,
        open_url=runtime.opener.open,
        sleep=config.sleep,
    )
    if "error" in fetched:
        state.records.append(
            {
                "url": url,
                "status": "error",
                "error": fetched["error"],
                "error_type": fetched.get("error_type", "network"),
                "attempts": fetched["attempts"],
            }
        )
        _write_progress(config, state)
        return
    state.records.append(_captured_record(runtime, url, fetched))
    _enqueue_page_links(runtime, fetched)
    _write_progress(config, state)
    if config.delay_seconds:
        config.sleep(config.delay_seconds)


def _run_crawl(runtime: CrawlRuntime) -> None:
    state = runtime.state
    while state.pending and len(state.records) < runtime.config.max_pages:
        url = state.pending.popleft()
        if url in state.visited:
            continue
        state.visited.add(url)
        _process_crawl_url(runtime, url)


def crawl_site(
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
    config = CrawlConfig(
        start_url=normalize_url(start_url),
        output_dir=output_dir,
        max_pages=max_pages,
        delay_seconds=delay_seconds,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        retries=retries,
        resume=resume,
        max_response_bytes=max_response_bytes,
        allow_private_networks=allow_private_networks,
        sleep=sleep,
    )
    _validate_crawl_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = config.output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    opener = urllib.request.build_opener(SameOriginRedirectHandler(config.start_url, config.allow_private_networks))
    runtime = CrawlRuntime(
        config=config,
        state=_load_crawl_state(config),
        pages_dir=pages_dir,
        opener=opener,
        robots=_robot_parser(config.start_url, config.user_agent, opener.open),
    )
    _run_crawl(runtime)
    manifest = {
        "id": stable_id("web", config.start_url, utc_now()),
        "kind": "website",
        "start_url": config.start_url,
        "captured_at": utc_now(),
        "max_pages": config.max_pages,
        "delay_seconds": config.delay_seconds,
        "timeout_seconds": config.timeout_seconds,
        "retries": config.retries,
        "max_response_bytes": config.max_response_bytes,
        "allow_private_networks": config.allow_private_networks,
        "user_agent": config.user_agent,
        "records": runtime.state.records,
        "truncated": bool(runtime.state.pending),
    }
    write_json(config.output_dir / "manifest.json", manifest)
    progress_path = config.output_dir / "progress.json"
    if not runtime.state.pending and progress_path.exists():
        progress_path.unlink()
    return manifest


# Backward-compatible Python API for existing integrations. New code should use crawl_site.
slurp_site = crawl_site
