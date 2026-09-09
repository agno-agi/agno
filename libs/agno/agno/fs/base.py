"""BaseFS: the storage backend for Agno FileSystem.

Backends store text files by ``(namespace, path)``.
Paths and namespace names are normalized by ``FileSystem``.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Set

from agno.fs._paths import build_chunk, path_sort_key
from agno.fs.errors import QuotaExceededError
from agno.fs.types import FileMeta, NamespaceUsage, SearchMatch


def _build_match(
    path: str, size_bytes: int, content: str, query: str, context_chars: int = 200
) -> Optional[SearchMatch]:
    """Build a ``SearchMatch`` for the first case-insensitive occurrence of ``query``.

    Returns ``None`` when the query does not occur. ``line`` locates the first
    occurrence so a caller can feed it straight to a ranged read, and
    ``match_count`` reports occurrences in the whole file so one snippet is not
    mistaken for the whole story.
    """
    lower_content = content.lower()
    lower_query = query.lower()
    idx = lower_content.find(lower_query)
    if idx == -1:
        return None
    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return SearchMatch(
        path=path,
        size_bytes=size_bytes,
        snippet=snippet,
        line=content.count("\n", 0, idx) + 1,
        match_count=lower_content.count(lower_query),
    )


class BaseFS(ABC):
    """Storage backend ABC: text files keyed by ``(namespace, path)``.

    Sync methods plus ``a``-prefixed async twins; the base class implements every
    async twin as ``asyncio.to_thread`` over the sync one, and backends override
    only when they have a native async client.
    """

    # ---- required core (every backend, object-store compatible) ----

    @abstractmethod
    def read(self, namespace: str, path: str) -> Optional[str]:
        """Return the file's content, or ``None`` if it does not exist."""
        ...

    @abstractmethod
    def write(self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None) -> FileMeta:
        """Create or replace a file. ``expected_version`` requests an atomic CAS.

        A backend that does not version its rows raises ``UnsupportedOperationError``
        when ``expected_version`` is passed.
        """
        ...

    @abstractmethod
    def list(self, namespace: str, directory: str = "") -> List[FileMeta]:
        """Return metadata for every file under ``directory`` (no content). Order is unspecified."""
        ...

    @abstractmethod
    def delete(self, namespace: str, path: str) -> bool:
        """Delete a file. Returns ``True`` if it existed. Idempotent."""
        ...

    # ---- capability-gated; base emulations provided ----

    def append(self, namespace: str, path: str, content: str, *, max_file_bytes: Optional[int] = None) -> FileMeta:
        """Append line-oriented content, creating the file if missing.

        Base emulation: read + concat + write, which is NOT atomic. The ``max_file_bytes``
        cap is checked against the content just read, so concurrent appenders can
        each pass the check and overshoot by up to one chunk.
        """
        chunk = build_chunk(content)
        if not chunk:
            existing_meta = self._stat(namespace, path)
            if existing_meta is not None:
                return existing_meta
            return FileMeta(path=path, size_bytes=0, version=None, updated_at=None)
        existing = self.read(namespace, path)
        if existing is None:
            new_content = chunk
        elif existing and not existing.endswith("\n"):
            new_content = existing + "\n" + chunk
        else:
            new_content = existing + chunk
        if max_file_bytes is not None:
            new_size = len(new_content.encode("utf-8"))
            if new_size > max_file_bytes:
                raise QuotaExceededError(
                    f"{path} would be {new_size} bytes (limit {max_file_bytes} per file)",
                    scope="file",
                    current=new_size,
                    limit=max_file_bytes,
                )
        return self.write(namespace, path, new_content)

    def move(self, namespace: str, src: str, dst: str, *, overwrite: bool = False) -> FileMeta:
        """Move or rename a file. Base emulation: read + write + delete, which is NOT atomic."""
        content = self.read(namespace, src)
        if content is None:
            raise FileNotFoundError(f"file not found: {src}")
        if src == dst:
            # A self-move is a no-op. Falling through would write dst then delete src
            # (== dst), destroying the file and returning a lying success.
            return self.write(namespace, dst, content)
        if not overwrite and self.read(namespace, dst) is not None:
            raise FileExistsError(f"file exists: {dst}")
        meta = self.write(namespace, dst, content)
        self.delete(namespace, src)
        return meta

    def search(self, namespace: str, query: str, directory: str = "", limit: int = 10) -> List[SearchMatch]:
        """Case-insensitive substring search. Base emulation: list + read + scan."""
        if not query:
            return []
        matches: List[SearchMatch] = []
        for meta in sorted(self.list(namespace, directory), key=lambda m: path_sort_key(m.path)):
            if len(matches) >= limit:
                break
            content = self.read(namespace, meta.path)
            if content is None:
                continue
            match = _build_match(meta.path, meta.size_bytes, content, query)
            if match is not None:
                matches.append(match)
        return matches

    def contains(self, namespace: str, lines: Sequence[str], directory: str = "") -> Set[str]:
        """Batch exact-line membership: return the subset of ``lines`` found as whole lines.

        Lines arrive already normalized by ``FileSystem``. Base emulation: list + read
        + line-set intersection over raw ``split("\\n")`` segments, which agrees
        byte-for-byte with the database backend's padded LIKE predicate.
        """
        remaining = set(lines)
        found: Set[str] = set()
        if not remaining:
            return found
        for meta in self.list(namespace, directory):
            if not remaining:
                break
            content = self.read(namespace, meta.path)
            if content is None:
                continue
            hit = remaining & set(content.split("\n"))
            found |= hit
            remaining -= hit
        return found

    def usage(self, namespace: str) -> NamespaceUsage:
        """Aggregate file count and total bytes. Base emulation: list + sum."""
        metas = self.list(namespace, "")
        return NamespaceUsage(file_count=len(metas), total_bytes=sum(m.size_bytes for m in metas))

    # ---- helpers ----

    def _stat(self, namespace: str, path: str) -> Optional[FileMeta]:
        """Return the file's metadata without content, or ``None`` if missing."""
        parent = "/".join(path.split("/")[:-1])
        for meta in self.list(namespace, parent):
            if meta.path == path:
                return meta
        return None

    # ---- async twins ----

    async def aread(self, namespace: str, path: str) -> Optional[str]:
        """Async variant of ``read``."""
        return await asyncio.to_thread(self.read, namespace, path)

    async def awrite(
        self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None
    ) -> FileMeta:
        """Async variant of ``write``."""
        return await asyncio.to_thread(self.write, namespace, path, content, expected_version=expected_version)

    async def alist(self, namespace: str, directory: str = "") -> List[FileMeta]:
        """Async variant of ``list``."""
        return await asyncio.to_thread(self.list, namespace, directory)

    async def adelete(self, namespace: str, path: str) -> bool:
        """Async variant of ``delete``."""
        return await asyncio.to_thread(self.delete, namespace, path)

    async def aappend(
        self, namespace: str, path: str, content: str, *, max_file_bytes: Optional[int] = None
    ) -> FileMeta:
        """Async variant of ``append``."""
        return await asyncio.to_thread(self.append, namespace, path, content, max_file_bytes=max_file_bytes)

    async def amove(self, namespace: str, src: str, dst: str, *, overwrite: bool = False) -> FileMeta:
        """Async variant of ``move``."""
        return await asyncio.to_thread(self.move, namespace, src, dst, overwrite=overwrite)

    async def asearch(self, namespace: str, query: str, directory: str = "", limit: int = 10) -> List[SearchMatch]:
        """Async variant of ``search``."""
        return await asyncio.to_thread(self.search, namespace, query, directory, limit)

    async def acontains(self, namespace: str, lines: Sequence[str], directory: str = "") -> Set[str]:
        """Async variant of ``contains``."""
        return await asyncio.to_thread(self.contains, namespace, lines, directory)

    async def ausage(self, namespace: str) -> NamespaceUsage:
        """Async variant of ``usage``."""
        return await asyncio.to_thread(self.usage, namespace)
