"""BaseFS: the storage backend for Agno FileSystem.

Backends store text files by ``(namespace, user_id, path)``. ``user_id`` is the
user partition: ``""`` is the shared partition every unbound operation uses,
and a bound user's files live in their own. Paths and namespace names are
normalized by ``FileSystem``.
"""

import asyncio
import inspect
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from agno.fs._paths import build_chunk, path_sort_key
from agno.fs.errors import QuotaExceededError, UnsupportedOperationError
from agno.fs.types import FileData, FileMeta, NamespaceUsage, SearchMatch


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


@lru_cache(maxsize=None)
def _takes_user_id(function: Callable[..., Any]) -> bool:
    try:
        return "user_id" in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False


def partition_kwargs(method: Callable[..., Any], user_id: str) -> Dict[str, Any]:
    """``{"user_id": ...}`` for a backend call into a user partition, ``{}`` for the shared one.

    ``user_id`` joined the backend contract after backends existed outside this
    package. A subclass whose methods predate it still serves the shared
    partition, but it cannot partition by user, so a call into a user partition
    fails closed rather than silently landing in the shared store.
    """
    if not user_id:
        return {}
    if _takes_user_id(getattr(method, "__func__", method)):
        return {"user_id": user_id}
    owner = getattr(method, "__self__", None)
    raise UnsupportedOperationError(
        f"{type(owner).__name__} does not partition files by user; its {method.__name__} takes no user_id",
        operation=method.__name__,
        backend=type(owner).__name__,
    )


class BaseFS(ABC):
    """Storage backend ABC: text files keyed by ``(namespace, user_id, path)``.

    Every method takes ``user_id``, the partition to act in; ``""`` is the shared
    partition. Sync methods plus ``a``-prefixed async twins; the base class
    implements every async twin as ``asyncio.to_thread`` over the sync one, and
    backends override only when they have a native async client.
    """

    # ---- required core (every backend, object-store compatible) ----

    @abstractmethod
    def read(self, namespace: str, path: str, *, user_id: str = "") -> Optional[str]:
        """Return the file's content, or ``None`` if it does not exist."""
        ...

    @abstractmethod
    def write(
        self,
        namespace: str,
        path: str,
        content: str,
        *,
        expected_version: Optional[int] = None,
        user_id: str = "",
    ) -> FileMeta:
        """Create or replace a file. ``expected_version`` requests an atomic CAS.

        A backend that does not version its rows raises ``UnsupportedOperationError``
        when ``expected_version`` is passed.
        """
        ...

    @abstractmethod
    def list(self, namespace: str, directory: str = "", *, user_id: str = "") -> List[FileMeta]:
        """Return metadata for every file under ``directory`` (no content). Order is unspecified."""
        ...

    @abstractmethod
    def delete(self, namespace: str, path: str, *, user_id: str = "") -> bool:
        """Delete a file. Returns ``True`` if it existed. Idempotent."""
        ...

    # ---- capability-gated; base emulations provided ----

    def read_with_meta(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileData]:
        """Read content and metadata from one backend snapshot when supported.

        The portable fallback derives size from the content returned by the one
        read instead of issuing a second metadata lookup that could observe a
        different version. Backends with versions or timestamps override this.
        """
        content = self.read(namespace, path, **partition_kwargs(self.read, user_id))
        if content is None:
            return None
        return FileData(
            content=content,
            meta=FileMeta(path=path, size_bytes=len(content.encode("utf-8")), user_id=user_id or None),
        )

    def append(
        self,
        namespace: str,
        path: str,
        content: str,
        *,
        max_file_bytes: Optional[int] = None,
        user_id: str = "",
    ) -> FileMeta:
        """Append line-oriented content, creating the file if missing.

        Base emulation: read + concat + write, which is NOT atomic. The ``max_file_bytes``
        cap is checked against the content just read, so concurrent appenders can
        each pass the check and overshoot by up to one chunk.
        """
        chunk = build_chunk(content)
        if not chunk:
            existing_meta = self._stat(namespace, path, user_id=user_id)
            if existing_meta is not None:
                return existing_meta
            return FileMeta(path=path, size_bytes=0, version=None, updated_at=None, user_id=user_id or None)
        existing = self.read(namespace, path, **partition_kwargs(self.read, user_id))
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
        return self.write(namespace, path, new_content, **partition_kwargs(self.write, user_id))

    def move(self, namespace: str, src: str, dst: str, *, overwrite: bool = False, user_id: str = "") -> FileMeta:
        """Move or rename a file. Base emulation: read + write + delete, which is NOT atomic."""
        read_kwargs = partition_kwargs(self.read, user_id)
        content = self.read(namespace, src, **read_kwargs)
        if content is None:
            raise FileNotFoundError(f"file not found: {src}")
        write_kwargs = partition_kwargs(self.write, user_id)
        if src == dst:
            # A self-move is a no-op. Falling through would write dst then delete src
            # (== dst), destroying the file and returning a lying success.
            return self.write(namespace, dst, content, **write_kwargs)
        if not overwrite and self.read(namespace, dst, **read_kwargs) is not None:
            raise FileExistsError(f"file exists: {dst}")
        meta = self.write(namespace, dst, content, **write_kwargs)
        self.delete(namespace, src, **partition_kwargs(self.delete, user_id))
        return meta

    def search(
        self, namespace: str, query: str, directory: str = "", limit: int = 10, *, user_id: str = ""
    ) -> List[SearchMatch]:
        """Case-insensitive substring search. Base emulation: list + read + scan."""
        if not query:
            return []
        matches: List[SearchMatch] = []
        read_kwargs = partition_kwargs(self.read, user_id)
        listed = self.list(namespace, directory, **partition_kwargs(self.list, user_id))
        for meta in sorted(listed, key=lambda m: path_sort_key(m.path)):
            if len(matches) >= limit:
                break
            content = self.read(namespace, meta.path, **read_kwargs)
            if content is None:
                continue
            match = _build_match(meta.path, meta.size_bytes, content, query)
            if match is not None:
                matches.append(match)
        return matches

    def contains(self, namespace: str, lines: Sequence[str], directory: str = "", *, user_id: str = "") -> Set[str]:
        """Batch exact-line membership: return the subset of ``lines`` found as whole lines.

        Lines arrive already normalized by ``FileSystem``. Base emulation: list + read
        + line-set intersection over raw ``split("\\n")`` segments, which agrees
        byte-for-byte with the database backend's padded LIKE predicate.
        """
        remaining = set(lines)
        found: Set[str] = set()
        if not remaining:
            return found
        read_kwargs = partition_kwargs(self.read, user_id)
        for meta in self.list(namespace, directory, **partition_kwargs(self.list, user_id)):
            if not remaining:
                break
            content = self.read(namespace, meta.path, **read_kwargs)
            if content is None:
                continue
            hit = remaining & set(content.split("\n"))
            found |= hit
            remaining -= hit
        return found

    def usage(self, namespace: str, *, user_id: str = "") -> NamespaceUsage:
        """Aggregate file count and total bytes. Base emulation: list + sum."""
        metas = self.list(namespace, "", **partition_kwargs(self.list, user_id))
        return NamespaceUsage(file_count=len(metas), total_bytes=sum(m.size_bytes for m in metas))

    def partitions(self, namespace: str) -> List[str]:
        """The user partitions holding files in ``namespace``, excluding the shared one.

        Base implementation: none. A backend that keeps partitions overrides it
        so an operator can see every user's files; one that does not has only
        the shared partition to show.
        """
        return []

    # ---- helpers ----

    def _stat(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileMeta]:
        """Return the file's metadata without content, or ``None`` if missing."""
        parent = "/".join(path.split("/")[:-1])
        for meta in self.list(namespace, parent, **partition_kwargs(self.list, user_id)):
            if meta.path == path:
                return meta
        return None

    # ---- async twins ----

    async def aread(self, namespace: str, path: str, *, user_id: str = "") -> Optional[str]:
        """Async variant of ``read``."""
        return await asyncio.to_thread(self.read, namespace, path, **partition_kwargs(self.read, user_id))

    async def aread_with_meta(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileData]:
        """Async variant of ``read_with_meta``."""
        return await asyncio.to_thread(
            self.read_with_meta, namespace, path, **partition_kwargs(self.read_with_meta, user_id)
        )

    async def awrite(
        self,
        namespace: str,
        path: str,
        content: str,
        *,
        expected_version: Optional[int] = None,
        user_id: str = "",
    ) -> FileMeta:
        """Async variant of ``write``."""
        return await asyncio.to_thread(
            self.write,
            namespace,
            path,
            content,
            expected_version=expected_version,
            **partition_kwargs(self.write, user_id),
        )

    async def alist(self, namespace: str, directory: str = "", *, user_id: str = "") -> List[FileMeta]:
        """Async variant of ``list``."""
        return await asyncio.to_thread(self.list, namespace, directory, **partition_kwargs(self.list, user_id))

    async def adelete(self, namespace: str, path: str, *, user_id: str = "") -> bool:
        """Async variant of ``delete``."""
        return await asyncio.to_thread(self.delete, namespace, path, **partition_kwargs(self.delete, user_id))

    async def aappend(
        self,
        namespace: str,
        path: str,
        content: str,
        *,
        max_file_bytes: Optional[int] = None,
        user_id: str = "",
    ) -> FileMeta:
        """Async variant of ``append``."""
        return await asyncio.to_thread(
            self.append,
            namespace,
            path,
            content,
            max_file_bytes=max_file_bytes,
            **partition_kwargs(self.append, user_id),
        )

    async def amove(
        self, namespace: str, src: str, dst: str, *, overwrite: bool = False, user_id: str = ""
    ) -> FileMeta:
        """Async variant of ``move``."""
        return await asyncio.to_thread(
            self.move, namespace, src, dst, overwrite=overwrite, **partition_kwargs(self.move, user_id)
        )

    async def asearch(
        self, namespace: str, query: str, directory: str = "", limit: int = 10, *, user_id: str = ""
    ) -> List[SearchMatch]:
        """Async variant of ``search``."""
        return await asyncio.to_thread(
            self.search, namespace, query, directory, limit, **partition_kwargs(self.search, user_id)
        )

    async def acontains(
        self, namespace: str, lines: Sequence[str], directory: str = "", *, user_id: str = ""
    ) -> Set[str]:
        """Async variant of ``contains``."""
        return await asyncio.to_thread(
            self.contains, namespace, lines, directory, **partition_kwargs(self.contains, user_id)
        )

    async def ausage(self, namespace: str, *, user_id: str = "") -> NamespaceUsage:
        """Async variant of ``usage``."""
        return await asyncio.to_thread(self.usage, namespace, **partition_kwargs(self.usage, user_id))

    async def apartitions(self, namespace: str) -> List[str]:
        """Async variant of ``partitions``."""
        return await asyncio.to_thread(self.partitions, namespace)
