"""Immutable results and safe errors for published documentation pages."""

from __future__ import annotations

import json
from typing import Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


class PageSearchConfig(BaseModel):
    """Transaction-local PostgreSQL planner options for page search.

    None inherits the database setting. Custom plans allow parameterized namespace
    queries to use their partial indexes. Parallel alternative queries always use
    zero PostgreSQL parallel workers to avoid multiplying worker fan-out.
    HNSW search breadth is configured only through PgVector's HNSW.ef_search.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    plan_cache_mode: Optional[Literal["auto", "force_custom_plan", "force_generic_plan"]] = "force_custom_plan"
    enable_seqscan: Optional[bool] = Field(default=None, strict=True)
    parallel_setup_cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, strict=True)
    parallel_tuple_cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False, strict=True)
    max_parallel_workers_per_gather: Optional[int] = Field(default=None, ge=0, le=1024, strict=True)
    # PostgreSQL measures this setting in blocks (normally 8 KiB), not bytes.
    min_parallel_table_scan_size: Optional[int] = Field(default=None, ge=0, le=2147483647, strict=True)


class PageError(Exception):
    code = "page_unavailable"

    def __init__(self, *, current_revision: Optional[str] = None):
        super().__init__(self.code)
        self.current_revision = current_revision


class PageNotFound(PageError):
    code = "page_not_found"


class PageChanged(PageError):
    code = "page_changed"


class SearchUnavailable(PageError):
    code = "search_unavailable"


class SyncFailed(PageError):
    code = "sync_failed"


class PageResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1


class Page(PageResult):
    content_id: str
    namespace: str
    path: str
    url: str
    title: str
    revision: str
    digest: str
    index_fingerprint: str
    filesystem_version: int
    expected_chunk_count: int


class SearchHit(PageResult):
    path: str
    url: str
    title: str
    revision: str
    chunk_id: str
    content: str
    score: float
    rank: int


class SearchResult(PageResult):
    results: Tuple[SearchHit, ...] = ()
    partial: bool = False
    truncated: bool = False
    omitted_count: int = 0
    warnings: Tuple[str, ...] = ()


class PageRead(PageResult):
    path: str
    url: str
    title: str
    revision: str
    text: str
    offset: int
    next_offset: Optional[int]
    total_chars: int
    truncated: bool


class PageList(PageResult):
    pages: Tuple[Page, ...] = ()
    next_cursor: Optional[str] = None
    restart_required: bool = False


class GrepMatch(PageResult):
    path: str
    url: str
    revision: str
    line_number: int
    text: str


class GrepResult(PageResult):
    matches: Tuple[GrepMatch, ...] = ()
    complete: bool = True
    stop_reason: Optional[Literal["limit", "output_limit", "deadline"]] = None


class SyncReport(PageResult):
    status: Literal["unchanged", "completed", "partial"]
    discovered: int = 0
    updated: int = 0
    deleted: int = 0
    failed: int = 0
    unknown: int = 0
    errors: Tuple[str, ...] = ()


def encoded_size(value: BaseModel) -> int:
    return len(value.model_dump_json().encode("utf-8"))


def tool_error(error: Exception) -> str:
    data = {"schema_version": 1, "error": error.code if isinstance(error, PageError) else "invalid_request"}
    if isinstance(error, PageChanged) and error.current_revision:
        data["current_revision"] = error.current_revision
    return json.dumps(data)
