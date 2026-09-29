"""Bounded discovery and same-origin fetching for documentation page syncs."""

from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import httpx

from agno.fs._paths import normalize_path
from agno.knowledge.page.types import SyncFailed
from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader
from agno.utils.bounded import WorkBudget


def page_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or "//" in path or "\\" in path:
        raise ValueError("invalid_page_path")
    if re.search(r"%(?![0-9a-fA-F]{2})|%(?:2f|5c|25)", path, re.I):
        raise ValueError("invalid_page_encoding")
    path = unquote(path, errors="strict")
    if "?" in path or "#" in path:
        raise ValueError("invalid_page_path")
    path = "/index.md" if path == "/" else path if path.endswith(".md") else path + ".md"
    return "/" + normalize_path(path[1:])


def page_prefix(prefix: str) -> str:
    if prefix == "/":
        return prefix
    trailing = prefix.endswith("/")
    canonical = page_path(prefix.rstrip("/"))
    if not prefix.endswith(".md"):
        canonical = canonical[:-3]
    return canonical + ("/" if trailing else "")


def source_url(url: str) -> str:
    if not isinstance(url, str) or len(url.encode("utf-8")) > 2048 or any(ord(c) < 33 for c in url):
        raise ValueError("invalid_source_url")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("invalid_source_url")
    if parts.port not in (None, 443):
        raise ValueError("invalid_source_port")
    page_path(parts.path or "/")
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", "", ""))


@dataclass(frozen=True)
class SourcePage:
    path: str
    url: str
    title: str
    citation_url: str


class PageSource:
    max_pages = 20_000
    max_indexes = 100
    max_depth = 3
    max_index_bytes = 8 * 1024 * 1024
    max_page_bytes = 4 * 1024 * 1024

    def __init__(self, url: str, public_url: Optional[str], budget: WorkBudget):
        self.url = source_url(url)
        self.base = self.url.rsplit("/", 1)[0]
        self.public = source_url(public_url or self.base).rstrip("/")
        self.origin = urlsplit(self.url).netloc
        self.budget = budget
        self.complete = True
        self.reader = LLMsTxtReader(skip_optional=False)

    def fetch(self, url: str, max_bytes: int) -> str:
        """Pin validated DNS answers to the connection while retaining TLS hostname checks."""
        url = source_url(url)
        deadline = time.monotonic() + min(30, self.budget.remaining())
        for attempt in range(3):
            current = url
            try:
                for redirect in range(4):
                    self.budget.remaining()
                    parts = urlsplit(current)
                    if parts.netloc != self.origin:
                        raise SyncFailed()
                    from dns.resolver import NoAnswer, Resolver

                    resolver = Resolver()
                    addresses: list[str] = []
                    assert parts.hostname is not None
                    for family in ("A", "AAAA"):
                        try:
                            answers = resolver.resolve(parts.hostname, family, lifetime=min(3, self.budget.remaining()))
                            addresses.extend(str(answer) for answer in answers)
                        except NoAnswer:
                            continue
                    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                        raise SyncFailed()
                    address = addresses[0]
                    authority = "[" + address + "]" if ":" in address else address
                    pinned = urlunsplit(("https", authority, parts.path, "", ""))
                    remaining = min(deadline - time.monotonic(), self.budget.remaining())
                    if remaining <= 0:
                        raise TimeoutError()
                    with httpx.Client(timeout=remaining, trust_env=False, follow_redirects=False) as client:
                        with client.stream(
                            "GET",
                            pinned,
                            headers={"Host": self.origin},
                            extensions={"sni_hostname": parts.hostname},
                        ) as response:
                            if response.is_redirect:
                                if redirect == 3:
                                    raise SyncFailed()
                                current = source_url(urljoin(current, response.headers["location"]))
                                continue
                            response.raise_for_status()
                            body = bytearray()
                            for chunk in response.iter_bytes():
                                self.budget.remaining()
                                if time.monotonic() > deadline or len(body) + len(chunk) > max_bytes:
                                    raise SyncFailed()
                                body.extend(chunk)
                            return body.decode("utf-8", errors="strict")
                raise SyncFailed()
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError) as exc:
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code != 429
                    and exc.response.status_code < 500
                ):
                    raise SyncFailed() from exc
                if attempt == 2:
                    raise SyncFailed() from exc
                delay = min(0.25 * 2**attempt, self.budget.remaining())
                if self.budget.cancelled.wait(delay):
                    self.budget.remaining()
                if time.monotonic() >= deadline:
                    raise SyncFailed() from exc
        raise SyncFailed()

    def discover(self) -> Dict[str, SourcePage]:
        pages: Dict[str, SourcePage] = {}
        visited: set[str] = set()
        collisions: set[str] = set()

        def visit(index: str, depth: int) -> None:
            if index in visited:
                return
            if depth > self.max_depth or len(visited) >= self.max_indexes:
                self.complete = False
                return
            visited.add(index)
            try:
                content = self.fetch(index, self.max_index_bytes)
            except Exception:
                self.complete = False
                return
            # The reader's parser accepts sectioned indexes. A leading section also
            # exposes flat indexes without dropping their links as overview text.
            _, entries = self.reader.parse_llms_txt("## Pages\n" + content, index)
            if not entries:
                self.complete = False
            for entry in entries:
                try:
                    target = source_url(entry.url)
                    if urlsplit(target).netloc != self.origin or not target.startswith(self.base + "/"):
                        raise ValueError("invalid_source_destination")
                    relative = target[len(self.base) :]
                    if relative.endswith("/llms.txt") or relative.startswith("/_llms/"):
                        visit(target, depth + 1)
                        continue
                    # Fumadocs links can identify the rendered page through an
                    # llms.mdx route while its resolved Markdown is served at .md.
                    if relative.startswith("/llms.mdx/"):
                        relative = relative[len("/llms.mdx") :]
                        base_path = urlsplit(self.base).path.rstrip("/")
                        if base_path and (relative == base_path or relative.startswith(base_path + "/")):
                            relative = relative[len(base_path) :] or "/"
                        target = self.base + relative
                    if relative.startswith("/_snippets/") or relative.endswith("/llms-full.txt"):
                        continue
                    path = page_path(relative)
                    if len(entry.title) > 512:
                        raise ValueError("title_too_long")
                    citation = self.public + ("/" if path == "/index.md" else quote(path[:-3], safe="/"))
                    source_url(citation)
                    fetch_url = (
                        self.base + "/index.md"
                        if relative == "/"
                        else target
                        if target.endswith(".md")
                        else target + ".md"
                    )
                    page = SourcePage(path, fetch_url, entry.title, citation)
                    if path in collisions:
                        raise ValueError("page_path_collision")
                    if path in pages and pages[path].url == page.url:
                        continue
                    if path in pages:
                        collisions.add(path)
                        del pages[path]
                        raise ValueError("page_path_collision")
                    if len(pages) >= self.max_pages and path not in pages:
                        self.complete = False
                        continue
                    pages[path] = page
                except Exception:
                    self.complete = False

        visit(self.url, 0)
        if not pages:
            raise SyncFailed()
        return pages
