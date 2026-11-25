"""The Company file system: every Company file in one store, at its path in the tree.

    wiki/
    goals/<goal-id>/
    tasks/<task-id>/
    notes/

The store is the namespace ``company`` of the Company database. It is shared: it belongs to the
company and is not partitioned by user. One size limit covers the whole store.

A version of Agno before 3.3.0 kept each folder in a namespace of its own, and notes in the AgentOS
database. Until the 3.3.0 migration has moved them the store refuses every use, with the error that
names the migration: files left where they were would look like an empty store.
"""

import os
from contextlib import contextmanager
from dataclasses import replace
from functools import lru_cache
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set
from weakref import WeakKeyDictionary, WeakSet

from agno.exceptions import MigrationRequiredError
from agno.fs import FileSystem
from agno.fs._paths import MAX_PATH_CHARS, MAX_SEGMENT_CHARS, MAX_SEGMENTS, normalize_path
from agno.fs.base import BaseFS, partition_kwargs
from agno.fs.errors import FileSystemError, InvalidPathError
from agno.fs.types import FileData, FileMeta, NamespaceUsage, SearchMatch

COMPANY_NAMESPACE = "company"
# The size limit of the whole store when CompanyConfig sets none.
COMPANY_FILESYSTEM_BYTES = 1_000_000_000

# The limit set for a database, by where the database is, so every handle on it has the same limit.
_limits: Dict[tuple, int] = {}
# A database kept in memory belongs to the handle that opened it.
_memory_limits: "WeakKeyDictionary[Any, int]" = WeakKeyDictionary()


def _where(db: Any) -> Optional[tuple]:
    """Where a database is, read from its URL: the same for a path written two ways. None when it is in memory."""
    engine = getattr(db, "db_engine", None)
    url = getattr(getattr(engine, "sync_engine", engine), "url", None)
    if url is None:
        return None
    database = url.database
    if url.get_backend_name() == "sqlite":
        if not database or database == ":memory:":
            return None
        database = os.path.realpath(database)
    return (url.get_backend_name(), url.host or url.query.get("host"), url.port, database)


def set_company_filesystem_bytes(db: Any, max_bytes: int) -> None:
    """Set the size limit of the Company file system in this database, for every handle on it."""
    where = _where(db)
    if where is None:
        _memory_limits[db] = max_bytes
    else:
        _limits[where] = max_bytes


def company_filesystem_bytes(db: Any) -> int:
    """The size limit of the Company file system in this database."""
    where = _where(db)
    if where is None:
        return _memory_limits.get(db, COMPANY_FILESYSTEM_BYTES)
    return _limits.get(where, COMPANY_FILESYSTEM_BYTES)


# Stand in a folder name as they are. Every other byte of an id is escaped, "%" included.
_FOLDER_NAME_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-_@+")


def folder_name(record_id: str) -> str:
    """The folder of a Goal or a Task under ``goals/`` or ``tasks/``: its id as one path segment.

    ASCII letters, digits and ``. - _ @ +`` stand as they are, with their case. Every other byte of
    the id in UTF-8 is written ``%xx``, the ``%`` sign included. Two ids never share a folder: not
    ids that differ by case, by a slash, or by the Unicode form of one letter. The name is plain
    ASCII, so no path rule changes it. An id made of one or two dots has its first dot escaped,
    because ``.`` and ``..`` are not names a path may hold.
    """
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("A Goal or Task id is a non-empty string")
    encoded = record_id.encode("utf-8", "surrogatepass")
    name = "".join(chr(byte) if chr(byte) in _FOLDER_NAME_SAFE else f"%{byte:02x}" for byte in encoded)
    return "%2e" + name[1:] if name in (".", "..") else name


# Databases whose file table holds no Company file that waits to be moved. Files do not move back.
_moved: "WeakSet[Any]" = WeakSet()


def _files_wait_error(table_name: str) -> MigrationRequiredError:
    return MigrationRequiredError(
        table_name=table_name,
        message=(
            f"Table {table_name} holds Company files where a version of Agno before 3.3.0 stored them, and the "
            "Company file system does not serve them from there. Apply the pending migrations with "
            "`asyncio.run(MigrationManager(db).up())` (import it from `agno.db.migrations.manager`; await the "
            "call directly in async code), or via the AgentOS endpoint `POST /databases/all/migrate`. Each file "
            "keeps its content, version and timestamps."
        ),
    )


def _require_files_moved(backend: Any) -> None:
    """Refuse to use the store while the migration still has a Company file to move."""
    db = backend.db
    if db in _moved:
        return
    from agno.db.migrations.versions.v3_3_0 import _files_wait

    with backend._connection() as conn:
        waiting = _files_wait(conn, db)
    if waiting:
        raise _files_wait_error(backend.table.fullname)
    _moved.add(db)


@lru_cache(maxsize=None)
def _store_backend(base: Any) -> Any:
    """The file table backend as the Company file system uses it."""

    class CompanyStore(base):  # type: ignore[misc, valid-type]
        """Every operation first makes sure the table is there. Here it also makes sure no file waits."""

        def _ensure_table(self) -> None:
            super()._ensure_table()
            _require_files_moved(self)

    return CompanyStore


def company_filesystem(db: Any) -> FileSystem:
    """The Company file system in a database: the whole tree, one store."""
    if not hasattr(db, "db_engine"):
        raise NotImplementedError("Company files require a supported FileSystem database")
    from agno.db.base import AsyncBaseDb
    from agno.fs.db import AsyncDbFileSystem, DbFileSystem

    try:
        if isinstance(db, AsyncBaseDb):
            backend = _store_backend(AsyncDbFileSystem)(db)
        else:
            backend = _store_backend(DbFileSystem)(db=db)
        return FileSystem(
            backend=backend,
            namespace=COMPANY_NAMESPACE,
            user_scoped=False,
            max_namespace_bytes=company_filesystem_bytes(db),
        )
    except (TypeError, ValueError) as exc:
        raise NotImplementedError("Company files require a supported FileSystem database") from exc


# Notes left in the AgentOS database

# The AgentOS database of a Company database that is kept apart from it: where notes were before 3.3.0.
_notes_sources: "WeakKeyDictionary[Any, Any]" = WeakKeyDictionary()
# Company databases whose AgentOS database holds no note to move, and those known to hold one.
_notes_moved: "WeakSet[Any]" = WeakSet()
_notes_wait: "WeakSet[Any]" = WeakSet()


def set_company_notes_source(company_db: Any, source_db: Any) -> None:
    """Name the AgentOS database of a Company database kept apart from it."""
    _notes_sources[company_db] = source_db


def _notes_wait_error() -> MigrationRequiredError:
    return MigrationRequiredError(
        table_name="company/notes",
        message=(
            "Notes are stored in the AgentOS database, and from 3.3.0 they belong in the Company database. "
            "Move them once with `move_company_notes(agent_os_db, company_db)` (import it from "
            "`agno.db.migrations.versions.v3_3_0`; use `await amove_company_notes(...)` when either database "
            "is asynchronous). Each note keeps its content, version and timestamps."
        ),
    )


def require_company_notes_moved(company_db: Any) -> None:
    """Refuse notes/ while the AgentOS database still holds notes that belong in the Company database."""
    source = _notes_sources.get(company_db)
    if source is None or company_db in _notes_moved:
        return
    from agno.db.base import AsyncBaseDb

    if isinstance(source, AsyncBaseDb) or isinstance(company_db, AsyncBaseDb):
        # An asynchronous database cannot be asked from here: what the last asynchronous use found stands.
        if company_db in _notes_wait:
            raise _notes_wait_error()
        return
    from agno.db.migrations.versions.v3_3_0 import company_notes_to_move

    _settle_notes(company_db, company_notes_to_move(source, company_db))


async def arequire_company_notes_moved(company_db: Any) -> None:
    """Async variant of ``require_company_notes_moved``. Either database may be synchronous."""
    source = _notes_sources.get(company_db)
    if source is None or company_db in _notes_moved:
        return
    from agno.db.migrations.versions.v3_3_0 import acompany_notes_to_move

    _settle_notes(company_db, await acompany_notes_to_move(source, company_db))


def _settle_notes(company_db: Any, waiting: bool) -> None:
    if waiting:
        _notes_wait.add(company_db)
        raise _notes_wait_error()
    _notes_wait.discard(company_db)
    _notes_moved.add(company_db)


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

    def _to_write(self, path: str) -> str:
        """The stored path of a file to write. The limits of a path count the folder's own name."""
        stored = self._inside(path)
        try:
            normalize_path(stored)
        except InvalidPathError:
            names = MAX_SEGMENTS - self.folder.count("/") - 1
            chars = MAX_PATH_CHARS - len(self.folder) - 1
            raise InvalidPathError(
                f"invalid path {path!r}: inside {self.folder}/ a path is at most {names} names deep and {chars} "
                f"characters, each name at most {MAX_SEGMENT_CHARS} characters."
            ) from None
        return stored

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
            return self._meta(self.backend.write(namespace, self._to_write(path), content, **kwargs))

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
            return self._meta(self.backend.append(namespace, self._to_write(path), content, **kwargs))

    def move(self, namespace: str, src: str, dst: str, *, overwrite: bool = False, user_id: str = "") -> FileMeta:
        kwargs = self._kwargs(self.backend.move, user_id, overwrite=overwrite)
        with self._named_inside():
            return self._meta(self.backend.move(namespace, self._inside(src), self._to_write(dst), **kwargs))

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

    def partitions(self, namespace: str) -> List[str]:
        return self.backend.partitions(namespace)

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
            return self._meta(await self.backend.awrite(namespace, self._to_write(path), content, **kwargs))

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
            return self._meta(await self.backend.aappend(namespace, self._to_write(path), content, **kwargs))

    async def amove(
        self, namespace: str, src: str, dst: str, *, overwrite: bool = False, user_id: str = ""
    ) -> FileMeta:
        kwargs = self._kwargs(self.backend.move, user_id, overwrite=overwrite)
        with self._named_inside():
            return self._meta(await self.backend.amove(namespace, self._inside(src), self._to_write(dst), **kwargs))

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

    async def apartitions(self, namespace: str) -> List[str]:
        return await self.backend.apartitions(namespace)
