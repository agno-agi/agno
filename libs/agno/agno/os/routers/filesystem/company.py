"""The Company filesystem as a caller of the /filesystem routes reads it."""

from typing import TYPE_CHECKING, Any, List, Optional, Set

from fastapi import HTTPException, Request

from agno.fs.base import BaseFS, partition_kwargs
from agno.fs.types import FileData, FileMeta, NamespaceUsage, SearchMatch
from agno.os.auth import build_insufficient_permissions_detail

if TYPE_CHECKING:
    from agno.fs import FileSystem

_WIKI, _TASKS = "wiki:read", "tasks:read"


class CompanyAccess:
    """What a caller may read of the Company filesystem: the rules of the Company routes.

    ``wiki:read`` reads the tree, and the files of Tasks need ``tasks:read`` as well.
    """

    def __init__(self, wiki: bool, tasks: bool):
        self.wiki = wiki
        self.tasks = wiki and tasks

    def missing(self) -> List[str]:
        return [_WIKI] if not self.wiki else [_TASKS]


async def get_company_access(request: Request) -> CompanyAccess:
    """The caller's access, decided as the Company tools decide it."""
    from agno.os.authz.run_context import request_authorization

    authority = request_authorization(request)
    if authority is None:
        return CompanyAccess(True, True)

    async def allowed(resource: str) -> bool:
        try:
            await authority.arequire(resource, "read")
        except PermissionError:
            return False
        return True

    wiki = await allowed("wiki")
    return CompanyAccess(wiki, wiki and await allowed("tasks"))


def denied(access: CompanyAccess) -> HTTPException:
    return HTTPException(status_code=403, detail=build_insufficient_permissions_detail(access.missing()))


def _area(path: str) -> str:
    return path.split("/", 1)[0]


class CompanyPageBackend(BaseFS):
    """Reads the Company filesystem within a caller's access. It writes nothing.

    A request for a folder the caller may not read is refused, and a listing of the whole tree leaves
    it out. ``notes/`` is refused while the notes wait to be moved, as the Company routes refuse it.
    """

    owns_reserved_namespace = True

    def __init__(self, backend: BaseFS, access: CompanyAccess, company_db: Any):
        self.backend = backend
        self.access = access
        self.company_db = company_db

    def _readable(self, path: str) -> bool:
        return self.access.wiki and (self.access.tasks or _area(path) != "tasks")

    async def _open(self, path: str) -> None:
        if not self._readable(path):
            raise denied(self.access)
        if _area(path) == "notes":
            await self.arequire_notes()

    async def arequire_notes(self) -> None:
        """Raise while notes wait in the AgentOS database."""
        from agno.company.filesystem import arequire_company_notes_moved

        await arequire_company_notes_moved(self.company_db)

    async def alist(self, namespace: str, directory: str = "", *, user_id: str = "") -> List[FileMeta]:
        await self._open(directory)
        rows = await self.backend.alist(namespace, directory, **partition_kwargs(self.backend.list, user_id))
        return [row for row in rows if self._readable(row.path)]

    async def aread(self, namespace: str, path: str, *, user_id: str = "") -> Optional[str]:
        data = await self.aread_with_meta(namespace, path, user_id=user_id)
        return None if data is None else data.content

    async def aread_with_meta(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileData]:
        await self._open(path)
        kwargs = partition_kwargs(self.backend.read_with_meta, user_id)
        return await self.backend.aread_with_meta(namespace, path, **kwargs)

    async def asearch(
        self, namespace: str, query: str, directory: str = "", limit: int = 10, *, user_id: str = ""
    ) -> List[SearchMatch]:
        await self._open(directory)
        kwargs = partition_kwargs(self.backend.search, user_id)
        # Matches the caller may not read must not use up the limit.
        stored = await self.backend.alist(namespace, directory, **partition_kwargs(self.backend.list, user_id))
        found = await self.backend.asearch(namespace, query, directory, max(len(stored), limit), **kwargs)
        return [match for match in found if self._readable(match.path)][:limit]

    async def ausage(self, namespace: str, *, user_id: str = "") -> NamespaceUsage:
        rows = await self.alist(namespace, user_id=user_id)
        return NamespaceUsage(file_count=len(rows), total_bytes=sum(row.size_bytes for row in rows))

    async def apartitions(self, namespace: str) -> List[str]:
        return await self.backend.apartitions(namespace)

    # The routes are asynchronous and read only.

    def _refuse(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("The Company filesystem is read through the asynchronous methods of this view")

    def list(self, namespace: str, directory: str = "", *, user_id: str = "") -> List[FileMeta]:
        return self._refuse()

    def read(self, namespace: str, path: str, *, user_id: str = "") -> Optional[str]:
        return self._refuse()

    def read_with_meta(self, namespace: str, path: str, *, user_id: str = "") -> Optional[FileData]:
        return self._refuse()

    def search(
        self, namespace: str, query: str, directory: str = "", limit: int = 10, *, user_id: str = ""
    ) -> List[SearchMatch]:
        return self._refuse()

    def usage(self, namespace: str, *, user_id: str = "") -> NamespaceUsage:
        return self._refuse()

    def write(
        self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None, user_id: str = ""
    ) -> FileMeta:
        return self._refuse()

    def delete(self, namespace: str, path: str, *, user_id: str = "", expected_version: Optional[int] = None) -> bool:
        return self._refuse()


def company_view(filesystem: "FileSystem", access: CompanyAccess, company_db: Any) -> "FileSystem":
    """The shared Company filesystem, read within the caller's access."""
    from agno.fs import FileSystem

    return FileSystem(
        CompanyPageBackend(filesystem.backend, access, company_db),
        namespace=filesystem.namespace,
        user_scoped=False,
        max_file_bytes=filesystem.max_file_bytes,
        max_namespace_bytes=filesystem.max_namespace_bytes,
    )


def holds_company_files(filesystem: "FileSystem", namespace: str) -> bool:
    """Whether the filesystem opens the shared Company files, through the Company store or another handle."""
    from agno.fs._reserved import is_reserved

    if filesystem.user_scoped:
        return False
    return bool(getattr(filesystem.backend, "owns_reserved_namespace", False)) or is_reserved(
        filesystem.backend, namespace
    )


def count_folders(paths: Set[str]) -> int:
    """Every distinct folder that holds one of the files, at any depth."""
    folders: Set[str] = set()
    for path in paths:
        folder = path.rpartition("/")[0]
        while folder and folder not in folders:
            folders.add(folder)
            folder = folder.rpartition("/")[0]
    return len(folders)
