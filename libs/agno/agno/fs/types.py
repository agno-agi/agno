from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Literal, Optional

if TYPE_CHECKING:
    from agno.fs.fs import FileSystem


@dataclass
class Mount:
    """One FileSystem mounted into another's tool surface under a top-level name.

    Declared by the developer via ``fs.tools(mounts={"shared": Mount(other_fs)})``
    (a bare ``FileSystem`` value coerces to a read-only Mount). The mount name
    becomes a top-level directory in the agent's view: paths whose first segment
    matches it route to ``fs`` instead of the primary store. ``mode`` is ``"ro"``
    (the default: reads only, writes return an error to the model) or ``"rw"``.
    ``fs`` may be templated; it resolves per tool call exactly like the primary.
    """

    fs: "FileSystem"
    mode: Literal["ro", "rw"] = "ro"


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
