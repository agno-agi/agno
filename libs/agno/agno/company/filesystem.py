"""The Company file system: every Company file in one store, at its path in the tree.

    wiki/
    goals/<goal-id>/
    tasks/<task-id>/
    notes/

The store is the namespace ``company`` of the Company database. It is shared: it belongs to the
company and is not partitioned by user. One size limit covers the whole store.
"""

from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Iterator, List, Optional, Sequence, Set
from weakref import WeakKeyDictionary

from agno.fs import FileSystem
from agno.fs._paths import normalize_path
from agno.fs.base import BaseFS, partition_kwargs
from agno.fs.errors import FileSystemError, InvalidPathError
from agno.fs.types import FileData, FileMeta, NamespaceUsage, SearchMatch

COMPANY_NAMESPACE = "company"
# The size limit of the whole store when CompanyConfig sets none.
COMPANY_FILESYSTEM_BYTES = 1_000_000_000

_limits: "WeakKeyDictionary[Any, int]" = WeakKeyDictionary()


def set_company_filesystem_bytes(db: Any, max_bytes: int) -> None:
    """Set the size limit of the Company file system in this database."""
    _limits[db] = max_bytes


def company_filesystem(db: Any) -> FileSystem:
    """The Company file system in a database: the whole tree, one store."""
    try:
        return FileSystem(
            db,
            namespace=COMPANY_NAMESPACE,
            user_scoped=False,
            max_namespace_bytes=_limits.get(db, COMPANY_FILESYSTEM_BYTES),
        )
    except (TypeError, ValueError) as exc:
        raise NotImplementedError("Company files require a supported FileSystem database") from exc


def company_folder(db: Any, folder: str) -> FileSystem:
    """One folder of the Company file system, as a file system of its own.

    Paths are inside the folder: ``brief.md`` in the folder ``goals/<goal-id>`` is the stored file
    ``goals/<goal-id>/brief.md``. No path reaches a file outside the folder. The size limit is the
    limit of the whole store.
    """
    whole = company_filesystem(db)
    return FileSystem(
        backend=_Folder(whole.backend, folder),
        namespace=COMPANY_NAMESPACE,
        user_scoped=False,
        max_namespace_bytes=whole.max_namespace_bytes,
    )


class _Folder(BaseFS):
    """A backend that reads and writes one folder of another backend.

    A path is sent to the backend with the folder in front of it and comes back without it, in a
    result and in an error. ``usage`` is the usage of the whole namespace, so the folder shares the
    namespace's size limit.
    """

    def __init__(self, backend: BaseFS, folder: str) -> None:
        self.backend = backend
        self.folder = normalize_path(folder)

    def _inside(self, path: str) -> str:
        """The stored path of a file in the folder. Only a normalized relative path names one."""
        if not isinstance(path, str) or not path or normalize_path(path) != path:
            raise InvalidPathError(f"invalid path {path!r}: it must be a normalized path inside {self.folder}/")
        return f"{self.folder}/{path}"

    def _directory(self, directory: str) -> str:
        return self._inside(directory) if directory else self.folder

    def _meta(self, meta: FileMeta) -> FileMeta:
        return replace(meta, path=meta.path[len(self.folder) + 1 :])

    def _data(self, data: Optional[FileData]) -> Optional[FileData]:
        return None if data is None else FileData(content=data.content, metadata=self._meta(data.metadata))

    def _match(self, match: SearchMatch) -> SearchMatch:
        return replace(match, path=match.path[len(self.folder) + 1 :])

    def _kwargs(self, method: Any, user_id: str, **extra: Any) -> dict:
        return {**partition_kwargs(method, user_id), **extra}

    @contextmanager
    def _named_inside(self) -> Iterator[None]:
        """Name a file by its path inside the folder in an error the backend raises."""
        try:
            yield
        except (FileSystemError, FileNotFoundError, FileExistsError) as exc:
            prefix = f"{self.folder}/"
            exc.args = tuple(arg.replace(prefix, "", 1) if isinstance(arg, str) else arg for arg in exc.args)
            raise

    # ---- sync ----

    def read(self, namespace: str, path: str, *, user_id: str = "") -> Optional[str]:
        return self.backend.read(namespace, self._inside(path), **self._kwargs(self.backend.read, user_id))

    def read_with_meta(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileData]:
        method = self.backend.read_with_meta
        return self._data(method(namespace, self._inside(path), **self._kwargs(method, user_id)))

    def write(
        self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None, user_id: str = ""
    ) -> FileMeta:
        kwargs = self._kwargs(self.backend.write, user_id, expected_version=expected_version)
        with self._named_inside():
            return self._meta(self.backend.write(namespace, self._inside(path), content, **kwargs))

    def list(self, namespace: str, directory: str = "", *, user_id: str = "") -> List[FileMeta]:
        kwargs = self._kwargs(self.backend.list, user_id)
        return [self._meta(meta) for meta in self.backend.list(namespace, self._directory(directory), **kwargs)]

    def delete(self, namespace: str, path: str, *, user_id: str = "", expected_version: Optional[int] = None) -> bool:
        kwargs = self._kwargs(self.backend.delete, user_id)
        if expected_version is not None:
            kwargs["expected_version"] = expected_version
        with self._named_inside():
            return self.backend.delete(namespace, self._inside(path), **kwargs)

    def append(
        self, namespace: str, path: str, content: str, *, max_file_bytes: Optional[int] = None, user_id: str = ""
    ) -> FileMeta:
        kwargs = self._kwargs(self.backend.append, user_id, max_file_bytes=max_file_bytes)
        with self._named_inside():
            return self._meta(self.backend.append(namespace, self._inside(path), content, **kwargs))

    def move(self, namespace: str, src: str, dst: str, *, overwrite: bool = False, user_id: str = "") -> FileMeta:
        kwargs = self._kwargs(self.backend.move, user_id, overwrite=overwrite)
        with self._named_inside():
            return self._meta(self.backend.move(namespace, self._inside(src), self._inside(dst), **kwargs))

    def search(
        self, namespace: str, query: str, directory: str = "", limit: int = 10, *, user_id: str = ""
    ) -> List[SearchMatch]:
        kwargs = self._kwargs(self.backend.search, user_id)
        found = self.backend.search(namespace, query, self._directory(directory), limit, **kwargs)
        return [self._match(match) for match in found]

    def contains(self, namespace: str, lines: Sequence[str], directory: str = "", *, user_id: str = "") -> Set[str]:
        kwargs = self._kwargs(self.backend.contains, user_id)
        return self.backend.contains(namespace, lines, self._directory(directory), **kwargs)

    def usage(self, namespace: str, *, user_id: str = "") -> NamespaceUsage:
        return self.backend.usage(namespace, **self._kwargs(self.backend.usage, user_id))

    def _stat(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileMeta]:
        meta = self.backend._stat(namespace, self._inside(path), **self._kwargs(self.backend._stat, user_id))
        return None if meta is None else self._meta(meta)

    # ---- async ----

    async def aread(self, namespace: str, path: str, *, user_id: str = "") -> Optional[str]:
        return await self.backend.aread(namespace, self._inside(path), **self._kwargs(self.backend.read, user_id))

    async def aread_with_meta(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileData]:
        kwargs = self._kwargs(self.backend.read_with_meta, user_id)
        return self._data(await self.backend.aread_with_meta(namespace, self._inside(path), **kwargs))

    async def awrite(
        self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None, user_id: str = ""
    ) -> FileMeta:
        kwargs = self._kwargs(self.backend.write, user_id, expected_version=expected_version)
        with self._named_inside():
            return self._meta(await self.backend.awrite(namespace, self._inside(path), content, **kwargs))

    async def alist(self, namespace: str, directory: str = "", *, user_id: str = "") -> List[FileMeta]:
        kwargs = self._kwargs(self.backend.list, user_id)
        found = await self.backend.alist(namespace, self._directory(directory), **kwargs)
        return [self._meta(meta) for meta in found]

    async def adelete(
        self, namespace: str, path: str, *, user_id: str = "", expected_version: Optional[int] = None
    ) -> bool:
        kwargs = self._kwargs(self.backend.delete, user_id)
        if expected_version is not None:
            kwargs["expected_version"] = expected_version
        with self._named_inside():
            return await self.backend.adelete(namespace, self._inside(path), **kwargs)

    async def aappend(
        self, namespace: str, path: str, content: str, *, max_file_bytes: Optional[int] = None, user_id: str = ""
    ) -> FileMeta:
        kwargs = self._kwargs(self.backend.append, user_id, max_file_bytes=max_file_bytes)
        with self._named_inside():
            return self._meta(await self.backend.aappend(namespace, self._inside(path), content, **kwargs))

    async def amove(
        self, namespace: str, src: str, dst: str, *, overwrite: bool = False, user_id: str = ""
    ) -> FileMeta:
        kwargs = self._kwargs(self.backend.move, user_id, overwrite=overwrite)
        with self._named_inside():
            return self._meta(await self.backend.amove(namespace, self._inside(src), self._inside(dst), **kwargs))

    async def asearch(
        self, namespace: str, query: str, directory: str = "", limit: int = 10, *, user_id: str = ""
    ) -> List[SearchMatch]:
        kwargs = self._kwargs(self.backend.search, user_id)
        found = await self.backend.asearch(namespace, query, self._directory(directory), limit, **kwargs)
        return [self._match(match) for match in found]

    async def acontains(
        self, namespace: str, lines: Sequence[str], directory: str = "", *, user_id: str = ""
    ) -> Set[str]:
        kwargs = self._kwargs(self.backend.contains, user_id)
        return await self.backend.acontains(namespace, lines, self._directory(directory), **kwargs)

    async def ausage(self, namespace: str, *, user_id: str = "") -> NamespaceUsage:
        return await self.backend.ausage(namespace, **self._kwargs(self.backend.usage, user_id))
