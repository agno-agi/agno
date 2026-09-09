"""Bounded prompt evidence assembled from ranked, revision-pinned page hits."""

from __future__ import annotations

import math
import time
from collections import defaultdict
from html import escape
from typing import TYPE_CHECKING, Callable, Literal, Optional, Tuple

from agno.knowledge.page.types import PageError, PageResult, SearchHit, SearchResult

if TYPE_CHECKING:
    from agno.knowledge.knowledge import Knowledge


class EvidencePage(PageResult):
    path: str
    url: str
    title: str
    revision: str
    content: str
    coverage: Literal["full", "excerpts", "truncated"]
    warnings: Tuple[str, ...] = ()


class PageEvidence(PageResult):
    """Only text is bounded by max_chars; structured metadata is for inspection."""

    text: str
    pages: Tuple[EvidencePage, ...] = ()
    omitted_pages: int = 0
    partial: bool = False
    truncated: bool = False
    warnings: Tuple[str, ...] = ()


def format_evidence_page(page: EvidencePage) -> str:
    """Format one page with escaped attributes and explicit evidence coverage."""
    attributes = " ".join(
        f'{key}="{escape(value, quote=True)}"'
        for key, value in (
            ("title", page.title),
            ("url", page.url),
            ("path", page.path),
            ("revision", page.revision),
            ("coverage", page.coverage),
        )
    )
    warning = "Warnings: " + ", ".join(page.warnings) + "\n\n" if page.warnings else ""
    return f"<page {attributes}>\n{warning}{page.content}\n</page>"


class _Assembly:
    def __init__(self, results: SearchResult, max_chars: int, timeout: float, formatter: Callable[[EvidencePage], str]):
        if type(max_chars) is not int or not 0 <= max_chars <= 2147483647:
            raise ValueError("max_chars must be an integer from 0 through 2147483647")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be positive and finite")
        self.results, self.max_chars, self.formatter = results, max_chars, formatter
        self.deadline = time.monotonic() + timeout
        self.groups: dict[tuple[str, str], list[SearchHit]] = defaultdict(list)
        for hit in sorted(results.results, key=lambda hit: hit.rank):
            self.groups[(hit.path, hit.revision)].append(hit)
        self.pages: list[EvidencePage] = []
        self.blocks: list[str] = []
        self.size = 0
        warnings = list(results.warnings)
        if results.partial:
            warnings.append("search_partial")
        if results.truncated or results.omitted_count:
            warnings.append(f"search_omitted:{results.omitted_count}")
        self.warnings = list(dict.fromkeys(warnings))
        if warnings:
            header = "Search warnings: " + ", ".join(self.warnings)
            if len(header) <= max_chars:
                self.blocks.append(header)
                self.size = len(header)

    def allowance(self) -> int:
        return max(0, self.max_chars - self.size - (2 if self.blocks else 0))

    def request(self, hits: list[SearchHit]) -> tuple[int, float]:
        # Reserve the actual formatter's metadata overhead before expanding a page.
        first = hits[0]
        empty = EvidencePage(
            path=first.path, url=first.url, title=first.title, revision=first.revision, content="", coverage="full"
        )
        return max(0, self.allowance() - len(self.formatter(empty))), max(0, self.deadline - time.monotonic())

    def add(self, hits: list[SearchHit], full: Optional[str], warning: Optional[str]) -> None:
        first = hits[0]
        content = full if full is not None else "\n\n[...]\n\n".join(f"## {hit.title}\n\n{hit.content}" for hit in hits)
        page = EvidencePage(
            path=first.path,
            url=first.url,
            title=first.title,
            revision=first.revision,
            content=content,
            coverage="full" if full is not None else "excerpts",
            warnings=(warning,) if warning else (),
        )
        allowed = self.allowance()
        block = self.formatter(page)
        # A custom formatter may add arbitrary overhead. Never clip its markup or
        # label a clipped full-page read as complete; shrink content and reformat.
        for _ in range(16):
            if len(block) <= allowed:
                self.pages.append(page)
                self.blocks.append(block)
                self.size += len(block) + (2 if len(self.blocks) > 1 else 0)
                return
            if not page.content:
                return
            keep = max(0, len(page.content) - max(1, len(block) - allowed))
            page = page.model_copy(update={"content": page.content[:keep], "coverage": "truncated"})
            block = self.formatter(page)

    def finish(self) -> PageEvidence:
        omitted = len(self.groups) - len(self.pages)
        return PageEvidence(
            text="\n\n".join(self.blocks),
            pages=tuple(self.pages),
            omitted_pages=omitted,
            partial=self.results.partial,
            truncated=self.results.truncated
            or self.results.omitted_count > 0
            or omitted > 0
            or any(p.coverage == "truncated" for p in self.pages),
            warnings=tuple(self.warnings),
        )


def render_page_evidence(
    knowledge: Knowledge,
    results: SearchResult,
    *,
    max_chars: int = 24000,
    timeout: float = 10,
    formatter: Callable[[EvidencePage], str] = format_evidence_page,
) -> PageEvidence:
    """Expand ranked hits using only their retrieved revisions, with excerpt fallback.

    max_chars bounds final text including metadata, warning text and separators in
    Unicode code points. timeout bounds expansion I/O across all pages; each read
    uses at most two seconds. Missing revisions never read the latest page. This
    performs no search/model call and stores no run or process cache. Return .text
    from a run dependency to reuse evidence on retries and choose prompt placement.
    A trusted formatter may change presentation; oversized metadata omits the page.
    """
    assembly = _Assembly(results, max_chars, timeout, formatter)
    for hits in assembly.groups.values():
        budget, remaining = assembly.request(hits)
        full, warning = None, None
        if not hits[0].revision:
            warning = "missing_revision"
        elif remaining <= 0:
            warning = "expansion_deadline"
        elif budget > 0:
            try:
                full = knowledge.read_full_page(
                    hits[0].path, revision=hits[0].revision, max_chars=budget, timeout=min(2, remaining)
                )
            except PageError as exc:
                warning = exc.code
        assembly.add(hits, full, warning)
    return assembly.finish()


async def arender_page_evidence(
    knowledge: Knowledge,
    results: SearchResult,
    *,
    max_chars: int = 24000,
    timeout: float = 10,
    formatter: Callable[[EvidencePage], str] = format_evidence_page,
) -> PageEvidence:
    """Async render_page_evidence; cancellation propagates through bounded reads."""
    assembly = _Assembly(results, max_chars, timeout, formatter)
    for hits in assembly.groups.values():
        budget, remaining = assembly.request(hits)
        full, warning = None, None
        if not hits[0].revision:
            warning = "missing_revision"
        elif remaining <= 0:
            warning = "expansion_deadline"
        elif budget > 0:
            try:
                full = await knowledge.aread_full_page(
                    hits[0].path, revision=hits[0].revision, max_chars=budget, timeout=min(2, remaining)
                )
            except PageError as exc:
                warning = exc.code
        assembly.add(hits, full, warning)
    return assembly.finish()
