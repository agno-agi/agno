from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FileMeta:
    """Metadata for one stored file."""

    path: str
    size_bytes: int
    version: Optional[int] = None  # None on backends without versioning
    updated_at: Optional[int] = None  # epoch seconds


@dataclass
class SearchMatch:
    """One file matching a content search."""

    path: str
    size_bytes: int
    snippet: str  # ~400-char window around the first match
    line: Optional[int] = None  # 1-indexed line the first match starts on
    match_count: int = 0  # occurrences in the whole file, not just the snippet


@dataclass
class ContainsResult:
    """Result of a batch exact-line membership check. Input order is preserved."""

    found: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


@dataclass
class NamespaceUsage:
    """Aggregate usage of a namespace."""

    file_count: int
    total_bytes: int
