import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.agent import Agent
from agno.fs import FileSystem, InvalidPathError
from agno.fs._paths import normalize_directory, normalize_path, path_sort_key
from agno.os.auth import (
    build_insufficient_permissions_detail,
    check_resource_access,
    get_accessible_resources,
    get_authentication_dependency,
)
from agno.os.middleware.user_scope import caller_is_admin, get_scoped_user_id
from agno.os.routers.filesystem.schema import (
    FileSystemContentResponse,
    FileSystemEntry,
    FileSystemListResponse,
    FileSystemSearchEntry,
    FileSystemSearchResponse,
    FileSystemTableEntry,
    FileSystemTableResponse,
    FileSystemUsage,
)
from agno.os.routers.filesystem.utils import _filesystem_backend_key
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_agent
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.app import AgentOS


_MAX_PREVIEW_CHARS = 100_000
_MAX_CONCURRENT_FILESYSTEM_READS = 8


async def _get_agent_filesystems(os: "AgentOS", agent_id: str, request: Request) -> list[FileSystem]:
    """Every filesystem the agent holds, resolved for the caller: the setting first, then its tools."""
    user_isolation_enabled = bool(getattr(request.state, "user_isolation_enabled", False))
    scoped_user_id = get_scoped_user_id(request)

    try:
        # The browser follows the other current-config AgentOS surfaces: an
        # authorized caller may browse the current draft as well as a published
        # config. Explicit version browsing remains outside this route.
        agent = await resolve_agent(
            agent_id,
            os.agents,
            os.db,
            os.registry,
            request=request,
            user_id=scoped_user_id,
            published_only=False,
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Error resolving filesystem agent '{agent_id}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not isinstance(agent, Agent):
        raise HTTPException(status_code=501, detail="This agent does not support filesystem browsing")
    try:
        filesystems = [filesystem for filesystem, _ in agent.filesystems]
    except Exception as e:
        log_error(f"Error initializing filesystem for agent '{agent_id}': {e}")
        raise HTTPException(status_code=503, detail="Agent filesystem is unavailable")
    if not filesystems:
        raise HTTPException(status_code=404, detail="This agent does not have a filesystem")
    effective_user_id = scoped_user_id or getattr(request.state, "user_id", None)
    if user_isolation_enabled and (not isinstance(effective_user_id, str) or not effective_user_id.strip()):
        raise HTTPException(status_code=403, detail="A user identity is required when user isolation is enabled")

    resolved: list[FileSystem] = []
    seen: set[tuple] = set()
    unresolved: Optional[InvalidPathError] = None
    for filesystem in filesystems:
        try:
            bound = filesystem._resolve_from_context(agent=agent, user_id=effective_user_id, agent_id=agent.id)
        except InvalidPathError as e:
            # One unbindable template must not hide the agent's other filesystems.
            unresolved = unresolved or e
            continue
        key = (_filesystem_backend_key(bound), bound.namespace)
        if key not in seen:
            seen.add(key)
            resolved.append(bound)
    if not resolved:
        raise HTTPException(status_code=400, detail=str(unresolved))
    return resolved


async def _resolve_filesystem(
    os: "AgentOS", request: Request, agent_id: Optional[str], namespace: Optional[str]
) -> tuple[FileSystem, list[str]]:
    """The one filesystem a browse request addresses, with the caller's agents that hold it.

    Storage is addressed by namespace. ``agent_id`` narrows the search to one agent,
    and alone selects that agent's first filesystem. Access always derives from the
    agents the caller may read, so a namespace no accessible agent holds is not found.
    """
    if agent_id is None and namespace is None:
        raise HTTPException(status_code=400, detail="Provide a namespace, an agent_id, or both")

    agent_ids = await _get_global_filesystem_agent_ids(os, request, agent_id)
    matches: dict[tuple, tuple[FileSystem, list[str]]] = {}
    for candidate_id in agent_ids:
        try:
            agent_filesystems = await _get_agent_filesystems(os, candidate_id, request)
        except HTTPException as e:
            if agent_id is None and e.status_code in (400, 404, 501):
                continue
            raise
        if namespace is None:
            agent_filesystems = agent_filesystems[:1]
        for filesystem in agent_filesystems:
            if namespace is not None and filesystem.namespace != namespace:
                continue
            key = (_filesystem_backend_key(filesystem), filesystem.namespace)
            matches.setdefault(key, (filesystem, []))[1].append(candidate_id)

    if not matches:
        # A namespace the caller's agents do not hold is indistinguishable from one that does not exist.
        raise HTTPException(status_code=404, detail="Filesystem not found")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Several filesystems use this namespace on different backends; pass agent_id to choose one",
        )
    filesystem, holders = next(iter(matches.values()))
    return filesystem, sorted(holders)


def _partition_views(filesystem: FileSystem, request: Request, user_id: Optional[str]) -> list[FileSystem]:
    """The partitions a browse request reads.

    A caller may name their own partition; an admin may name any user's, and
    with none named sees every partition of a user-scoped store: the shared one
    first, then each user's. Everyone else reads the store as their runs do.
    """
    if user_id is not None:
        own = get_scoped_user_id(request) or getattr(request.state, "user_id", None)
        if not caller_is_admin(request) and user_id != own:
            raise HTTPException(status_code=403, detail="Only an admin may browse another user's files")
        return [filesystem.partition(user_id)]
    if caller_is_admin(request) and filesystem.user_scoped:
        return [filesystem.partition(None)] + [filesystem.partition(user) for user in filesystem.partitions()]
    return [filesystem]


async def _apartition_views(filesystem: FileSystem, request: Request, user_id: Optional[str]) -> list[FileSystem]:
    """Async variant of ``_partition_views``."""
    if user_id is None and caller_is_admin(request) and filesystem.user_scoped:
        users = await filesystem.apartitions()
        return [filesystem.partition(None)] + [filesystem.partition(user) for user in users]
    return _partition_views(filesystem, request, user_id)


def _merge_entries(listings: list[list[FileSystemEntry]]) -> list[FileSystemEntry]:
    """Combine directory listings from several partitions: one row per directory, files kept per partition."""
    if len(listings) == 1:
        return listings[0]
    directories: Dict[str, FileSystemEntry] = {}
    files: list[FileSystemEntry] = []
    for listing in listings:
        for entry in listing:
            if entry.type == "file":
                files.append(entry)
                continue
            existing = directories.get(entry.path)
            if existing is None:
                directories[entry.path] = entry
            else:
                existing.size_bytes = (existing.size_bytes or 0) + (entry.size_bytes or 0)
                if entry.updated_at is not None:
                    existing.updated_at = max(existing.updated_at or entry.updated_at, entry.updated_at)
    return sorted(directories.values(), key=lambda entry: path_sort_key(entry.path)) + sorted(
        files, key=lambda entry: (path_sort_key(entry.path), entry.user_id or "")
    )


_USER_ID_QUERY = Query(
    None,
    description="User partition to browse: your own, or any user's for an admin. An admin who names none sees every partition",
)


def _list_entries(filesystem: FileSystem, directory: str) -> list[FileSystemEntry]:
    normalized_directory = normalize_directory(directory)
    prefix = f"{normalized_directory}/" if normalized_directory else ""
    directories: Dict[str, FileSystemEntry] = {}
    files: list[FileSystemEntry] = []

    for meta in filesystem.list(normalized_directory):
        relative_path = meta.path[len(prefix) :] if prefix and meta.path.startswith(prefix) else meta.path
        name, separator, _ = relative_path.partition("/")
        if separator:
            directory_path = f"{prefix}{name}" if prefix else name
            existing = directories.get(directory_path)
            if existing is None:
                directories[directory_path] = FileSystemEntry(
                    path=directory_path,
                    type="directory",
                    size_bytes=meta.size_bytes,
                    updated_at=meta.updated_at,
                )
            else:
                existing.size_bytes = (existing.size_bytes or 0) + meta.size_bytes
                if meta.updated_at is not None:
                    existing.updated_at = max(existing.updated_at or meta.updated_at, meta.updated_at)
            continue
        files.append(
            FileSystemEntry(
                path=meta.path,
                type="file",
                size_bytes=meta.size_bytes,
                version=meta.version,
                updated_at=meta.updated_at,
                user_id=meta.user_id,
            )
        )

    return sorted(directories.values(), key=lambda entry: path_sort_key(entry.path)) + sorted(
        files, key=lambda entry: path_sort_key(entry.path)
    )


async def _get_global_filesystem_agent_ids(
    os: "AgentOS", request: Request, requested_agent_id: Optional[str]
) -> list[str]:
    scopes_are_authoritative = bool(getattr(request.state, "authorization_enabled", False))
    if requested_agent_id:
        if scopes_are_authoritative and not check_resource_access(request, requested_agent_id, "agents", "read"):
            raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail(["agents:read"]))
        return [requested_agent_id]

    accessible_ids = get_accessible_resources(request, "agents") if scopes_are_authoritative else {"*"}
    if not accessible_ids:
        raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail(["agents:read"]))

    agent_ids = {
        agent_id for entry in os.agents or [] if isinstance((agent_id := getattr(entry, "id", None)), str) and agent_id
    }

    if os.db is not None:
        from agno.agent.agent import get_agents
        from agno.db.base import BaseDb

        if isinstance(os.db, BaseDb):
            stored_agents = await asyncio.to_thread(
                get_agents,
                db=os.db,
                registry=os.registry,
                exclude_component_ids=agent_ids or None,
                user_id=get_scoped_user_id(request),
            )
            agent_ids.update(
                agent_id
                for agent in stored_agents or []
                if isinstance((agent_id := getattr(agent, "id", None)), str) and agent_id
            )

    if "*" not in accessible_ids:
        agent_ids.intersection_update(accessible_ids)

    return sorted(agent_ids)


async def _get_global_files(
    os: "AgentOS",
    request: Request,
    agent_ids: list[str],
    *,
    namespace: Optional[str],
    query: Optional[str],
    strict: bool,
    user_id: Optional[str] = None,
) -> list[FileSystemTableEntry]:
    filesystems: dict[tuple, tuple[FileSystem, list[str]]] = {}
    for agent_id in agent_ids:
        try:
            agent_filesystems = await _get_agent_filesystems(os, agent_id, request)
        except HTTPException as e:
            if not strict and e.status_code in (400, 404, 501):
                continue
            raise

        for filesystem in agent_filesystems:
            if namespace is not None and filesystem.namespace != namespace:
                continue

            key = (_filesystem_backend_key(filesystem), filesystem.namespace)
            existing = filesystems.get(key)
            if existing is None:
                filesystems[key] = (filesystem, [agent_id])
            else:
                existing[1].append(agent_id)

    async def _read_files(store: FileSystem, linked_agent_ids: list[str]) -> list[FileSystemTableEntry]:
        views = await _apartition_views(store, request, user_id)
        rows: list[FileSystemTableEntry] = []
        for view in views:
            rows.extend(await _read_view(view, linked_agent_ids))
        return rows

    async def _read_view(filesystem: FileSystem, linked_agent_ids: list[str]) -> list[FileSystemTableEntry]:
        metadata = await filesystem.alist()
        if not query:
            return [
                FileSystemTableEntry(
                    namespace=filesystem.namespace,
                    path=item.path,
                    agent_ids=linked_agent_ids,
                    size_bytes=item.size_bytes,
                    version=item.version,
                    updated_at=item.updated_at,
                    user_id=item.user_id,
                )
                for item in metadata
            ]

        metadata_by_path = {item.path: item for item in metadata}
        matches = await filesystem.asearch(query, limit=max(len(metadata), 1))
        entries: list[FileSystemTableEntry] = []
        for match in matches:
            meta = metadata_by_path.get(match.path)
            entries.append(
                FileSystemTableEntry(
                    namespace=filesystem.namespace,
                    path=match.path,
                    agent_ids=linked_agent_ids,
                    size_bytes=match.size_bytes,
                    version=meta.version if meta else None,
                    updated_at=meta.updated_at if meta else None,
                    user_id=meta.user_id if meta else None,
                    snippet=match.snippet,
                    line=match.line,
                    match_count=match.match_count,
                )
            )
        return entries

    entries: list[FileSystemTableEntry] = []
    sources = list(filesystems.values())
    for start in range(0, len(sources), _MAX_CONCURRENT_FILESYSTEM_READS):
        batch = sources[start : start + _MAX_CONCURRENT_FILESYSTEM_READS]
        results = await asyncio.gather(
            *(_read_files(filesystem, linked_agent_ids) for filesystem, linked_agent_ids in batch)
        )
        for result in results:
            entries.extend(result)

    return sorted(
        entries,
        key=lambda entry: (entry.namespace.casefold(), path_sort_key(entry.path), entry.user_id or "", entry.agent_ids),
    )


def get_filesystem_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "/filesystem/files",
        response_model=FileSystemTableResponse,
        tags=["FileSystem"],
        operation_id="list_filesystem_files",
        summary="List Filesystem Files",
        description=(
            "List files across the configured agent filesystems visible to the caller. "
            "Use agent_id or namespace to narrow the result, and query to search file contents."
        ),
    )
    async def list_filesystem_files(
        request: Request,
        agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
        namespace: Optional[str] = Query(None, description="Filter by resolved namespace"),
        query: Optional[str] = Query(None, min_length=1, max_length=200, description="Search file contents"),
        user_id: Optional[str] = _USER_ID_QUERY,
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemTableResponse:
        agent_ids = await _get_global_filesystem_agent_ids(os, request, agent_id)
        entries = await _get_global_files(
            os,
            request,
            agent_ids,
            namespace=namespace,
            query=query.strip() if query else None,
            strict=agent_id is not None,
            user_id=user_id,
        )
        total_count = len(entries)
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        start = (page - 1) * limit
        return FileSystemTableResponse(
            entries=entries[start : start + limit],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get(
        "/filesystem/entries",
        response_model=FileSystemListResponse,
        tags=["FileSystem"],
        operation_id="list_filesystem_entries",
        summary="List Filesystem Entries",
        description="List the files and directories directly under a directory of one filesystem.",
    )
    async def list_filesystem_entries(
        request: Request,
        namespace: Optional[str] = Query(None, description="Resolved namespace of the filesystem to browse"),
        agent_id: Optional[str] = Query(
            None, description="Agent holding the filesystem; alone, selects that agent's first filesystem"
        ),
        directory: str = Query("", description="Relative directory inside the filesystem"),
        user_id: Optional[str] = _USER_ID_QUERY,
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemListResponse:
        filesystem, holder_ids = await _resolve_filesystem(os, request, agent_id, namespace)
        views = await _apartition_views(filesystem, request, user_id)
        try:
            normalized_directory = normalize_directory(directory)
            listings = [await asyncio.to_thread(_list_entries, view, normalized_directory) for view in views]
            entries = _merge_entries(listings)
            usages = [await view.ausage() for view in views]
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        file_count = sum(usage.file_count for usage in usages)
        total_bytes = sum(usage.total_bytes for usage in usages)

        total_count = len(entries)
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        start = (page - 1) * limit
        return FileSystemListResponse(
            namespace=filesystem.namespace,
            agent_ids=holder_ids,
            directory=normalized_directory,
            entries=entries[start : start + limit],
            usage=FileSystemUsage(
                file_count=file_count,
                total_bytes=total_bytes,
                bytes_limit=filesystem.max_namespace_bytes,
            ),
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get(
        "/filesystem/content",
        response_model=FileSystemContentResponse,
        tags=["FileSystem"],
        operation_id="read_filesystem_content",
        summary="Read Filesystem Content",
        description="Read a preview of one file, continuing from offset when the file is longer than limit.",
    )
    async def read_filesystem_content(
        request: Request,
        namespace: Optional[str] = Query(None, description="Resolved namespace of the filesystem to browse"),
        agent_id: Optional[str] = Query(
            None, description="Agent holding the filesystem; alone, selects that agent's first filesystem"
        ),
        path: str = Query(..., description="Relative file path inside the filesystem"),
        user_id: Optional[str] = _USER_ID_QUERY,
        offset: int = Query(0, ge=0, description="Character offset into the file"),
        limit: int = Query(_MAX_PREVIEW_CHARS, ge=1, le=_MAX_PREVIEW_CHARS, description="Characters to return"),
    ) -> FileSystemContentResponse:
        filesystem, holder_ids = await _resolve_filesystem(os, request, agent_id, namespace)
        # One file lives in one partition: an admin who names none reads the shared partition.
        filesystem = _partition_views(filesystem, request, user_id)[0]
        try:
            normalized_path = normalize_path(path)
            file_data = await filesystem.aread_with_meta(normalized_path)
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if file_data is None:
            raise HTTPException(status_code=404, detail="File not found")
        metadata = file_data.meta
        content = file_data.content
        end = min(offset + limit, len(content))
        preview = content[offset:end]
        return FileSystemContentResponse(
            namespace=filesystem.namespace,
            agent_ids=holder_ids,
            path=metadata.path,
            content=preview,
            size_bytes=metadata.size_bytes,
            version=metadata.version,
            updated_at=metadata.updated_at,
            user_id=metadata.user_id,
            line_count=0 if not content else content.count("\n") + (0 if content.endswith("\n") else 1),
            truncated=end < len(content),
            offset=offset,
            limit=limit,
            next_offset=end if end < len(content) else None,
        )

    @router.get(
        "/filesystem/search",
        response_model=FileSystemSearchResponse,
        tags=["FileSystem"],
        operation_id="search_filesystem",
        summary="Search Filesystem",
        description="Search file contents within one filesystem.",
    )
    async def search_filesystem(
        request: Request,
        namespace: Optional[str] = Query(None, description="Resolved namespace of the filesystem to browse"),
        agent_id: Optional[str] = Query(
            None, description="Agent holding the filesystem; alone, selects that agent's first filesystem"
        ),
        query: str = Query(..., min_length=1, max_length=200),
        directory: str = Query(""),
        user_id: Optional[str] = _USER_ID_QUERY,
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemSearchResponse:
        filesystem, holder_ids = await _resolve_filesystem(os, request, agent_id, namespace)
        views = await _apartition_views(filesystem, request, user_id)
        try:
            normalized_directory = normalize_directory(directory)
            matches: list[tuple[Any, Optional[str]]] = []
            for view in views:
                files = await view.alist(normalized_directory)
                found = await view.asearch(query, directory=normalized_directory, limit=max(len(files), 1))
                matches.extend((match, view.user_id) for match in found)
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))

        total_count = len(matches)
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        start = (page - 1) * limit
        return FileSystemSearchResponse(
            namespace=filesystem.namespace,
            agent_ids=holder_ids,
            query=query,
            directory=normalized_directory,
            entries=[
                FileSystemSearchEntry(
                    path=match.path,
                    size_bytes=match.size_bytes,
                    snippet=match.snippet,
                    line=match.line,
                    match_count=match.match_count,
                    user_id=view_user,
                )
                for match, view_user in matches[start : start + limit]
            ],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    return router
