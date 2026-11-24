import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Literal, NamedTuple, Optional, TypeVar, Union

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
from agno.os.routers.filesystem.utils import (
    _filesystem_backend_key,
    _filesystem_id_forms,
    _filesystem_ids,
    _filesystem_key,
    _match_filesystem_id,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginationInfo,
    SortOrder,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_agent
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.app import AgentOS


_MAX_PREVIEW_CHARS = 100_000

FileSortField = Literal["type", "size", "updated_at"]
_Entry = TypeVar("_Entry", bound=Union[FileSystemEntry, FileSystemTableEntry])


def _sort_entries(entries: List[_Entry], sort_by: Optional[FileSortField], sort_order: SortOrder) -> List[_Entry]:
    """Order a whole listing before it is paged; without ``sort_by`` the given order stands.

    Sorting by ``type`` puts directories first ascending and files first
    descending. Sorting by size or update time keeps directories ahead of files
    in either direction. Ties fall back to the path so a page boundary is stable.
    """
    if sort_by is None:
        return entries

    def value(entry: _Entry) -> Any:
        if sort_by == "type":
            return getattr(entry, "type", "file")
        if sort_by == "size":
            return entry.size_bytes or 0
        return entry.updated_at or 0

    ordered = sorted(entries, key=lambda entry: (value(entry), path_sort_key(entry.path)))
    if sort_order == SortOrder.DESC:
        ordered.reverse()
    if sort_by == "type":
        return ordered
    return [entry for entry in ordered if getattr(entry, "type", "file") == "directory"] + [
        entry for entry in ordered if getattr(entry, "type", "file") != "directory"
    ]


_SORT_BY_QUERY = Query(None, description="Sort by type, size or updated_at; the default order is by path")
_SORT_ORDER_QUERY = Query(SortOrder.ASC, description="Sort order (asc or desc)")
_MAX_CONCURRENT_FILESYSTEM_READS = 8


async def _get_agent_filesystems(os: "AgentOS", agent_id: str, request: Request) -> list[FileSystem]:
    """Every filesystem the agent holds, resolved for the caller: the setting first, then its tools."""
    user_isolation_enabled = bool(getattr(request.state, "user_isolation_enabled", False))
    scoped_user_id = get_scoped_user_id(request)

    try:
        # The browser follows the other current-config AgentOS surfaces: an
        # authorized caller may browse the current draft as well as a published
        # config. Explicit version browsing remains outside this route.
        # Browsing never runs the agent, so a stored agent whose tools this
        # registry cannot resolve still exposes its filesystem.
        agent = await resolve_agent(
            agent_id,
            os.agents,
            os.db,
            os.registry,
            request=request,
            user_id=scoped_user_id,
            published_only=False,
            strict=False,
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


_AMBIGUOUS_ID_DETAIL = "Several filesystems match this filesystem_id; pass the id /config lists for the one to read"


class _DeclaredFileSystem(NamedTuple):
    """A filesystem declared on the AgentOS, as the caller sees it."""

    key: tuple
    forms: tuple
    # Bound for the caller, or None with the reason the caller cannot bind it.
    filesystem: Optional[FileSystem]
    error: Optional[InvalidPathError]


class _Source(NamedTuple):
    """One filesystem a request may read, with the caller's agents that hold it."""

    filesystem: FileSystem
    agent_ids: list[str]
    forms: tuple


def _caller_user_id(request: Request) -> Optional[str]:
    return get_scoped_user_id(request) or getattr(request.state, "user_id", None)


def _get_declared_filesystems(os: "AgentOS", request: Request) -> list[_DeclaredFileSystem]:
    """The filesystems declared on the AgentOS, with their namespaces resolved for the caller.

    They stand without an agent, so reading one loads none. A namespace that
    uses ``{agent_id}`` or ``{team_id}`` is filled only by an agent that holds
    the store, so it is left to that agent. A store partitioned by user is bound
    to the caller, and one the caller cannot bind carries the reason.
    """
    user_id = _caller_user_id(request)
    declared: dict[tuple, _DeclaredFileSystem] = {}
    for filesystem in os.filesystems:
        if any(name != "user_id" for name in filesystem._placeholders):
            continue
        try:
            namespace = filesystem.resolve(user_id=user_id).namespace
        except InvalidPathError:
            # The caller's identity cannot be part of a namespace: the store is not theirs to browse.
            continue
        key = _filesystem_key(filesystem, namespace)
        if key in declared:
            # One store declared twice is one filesystem: the first declaration describes it.
            continue
        bound: Optional[FileSystem] = None
        error: Optional[InvalidPathError] = None
        try:
            bound = filesystem._resolve_from_context(user_id=user_id)
        except InvalidPathError as e:
            error = e
        declared[key] = _DeclaredFileSystem(key, _filesystem_id_forms(filesystem, namespace), bound, error)
    return list(declared.values())


async def _get_sources(
    os: "AgentOS", request: Request, agent_id: Optional[str], declared: list[_DeclaredFileSystem]
) -> dict[tuple, _Source]:
    """The filesystems a request may read, keyed by backend and namespace.

    ``agent_id`` narrows the search to that agent, and its errors are raised.
    With none the search covers the declared filesystems, then those of every
    agent the caller may read; an agent that cannot be browsed is left out.
    """
    sources: dict[tuple, _Source] = {}
    if agent_id is None:
        for entry in declared:
            if entry.filesystem is not None:
                sources[entry.key] = _Source(entry.filesystem, [], entry.forms)

    agent_ids = await _get_global_filesystem_agent_ids(os, request, agent_id, required=not declared)
    for candidate_id in agent_ids:
        try:
            agent_filesystems = await _get_agent_filesystems(os, candidate_id, request)
        except HTTPException as e:
            if agent_id is None and e.status_code in (400, 404, 501):
                continue
            raise
        for filesystem in agent_filesystems:
            key = _filesystem_key(filesystem)
            source = sources.get(key)
            if source is None:
                source = sources[key] = _Source(filesystem, [], _filesystem_id_forms(filesystem))
            source.agent_ids.append(candidate_id)
    return sources


async def _select_filesystems(
    os: "AgentOS",
    request: Request,
    agent_id: Optional[str],
    namespace: Optional[str],
    filesystem_id: Optional[str],
) -> tuple[list[tuple[str, _Source]], list[_DeclaredFileSystem]]:
    """The filesystems a request addresses, each with its id, and the declared ones considered.

    ``filesystem_id`` names one filesystem. One declared on the AgentOS is read
    without loading an agent; any other is found among the filesystems of the
    agents the caller may read. ``namespace`` keeps the filesystems resolving to
    it, and ``agent_id`` narrows the search to one agent.
    """
    declared = _get_declared_filesystems(os, request)
    declared_forms = [(entry.key, entry.forms) for entry in declared]

    if filesystem_id is not None and agent_id is None:
        declared_ids = _filesystem_ids(declared_forms)
        named = [
            declared[index]
            for index in _match_filesystem_id(
                filesystem_id, [(declared_ids[entry.key], entry.forms) for entry in declared]
            )
            if namespace is None or declared[index].forms[0] == namespace
        ]
        if len(named) > 1:
            raise HTTPException(status_code=409, detail=_AMBIGUOUS_ID_DETAIL)
        if named:
            if named[0].filesystem is None:
                raise HTTPException(status_code=400, detail=str(named[0].error))
            return [(declared_ids[named[0].key], _Source(named[0].filesystem, [], named[0].forms))], declared

    sources = await _get_sources(os, request, agent_id, declared)
    ids = _filesystem_ids(declared_forms, [(key, source.forms) for key, source in sources.items()])
    selected = [
        (ids[key], source)
        for key, source in sources.items()
        if namespace is None or source.filesystem.namespace == namespace
    ]
    if filesystem_id is not None:
        positions = _match_filesystem_id(filesystem_id, [(source_id, source.forms) for source_id, source in selected])
        if len(positions) > 1:
            raise HTTPException(status_code=409, detail=_AMBIGUOUS_ID_DETAIL)
        selected = [selected[index] for index in positions]
    return selected, declared


async def _resolve_filesystem(
    os: "AgentOS",
    request: Request,
    agent_id: Optional[str],
    namespace: Optional[str],
    filesystem_id: Optional[str] = None,
) -> tuple[FileSystem, list[str], str]:
    """The one filesystem a browse request addresses, with the caller's agents that hold it and its id.

    ``filesystem_id`` names it. Without one, storage is addressed by namespace:
    ``agent_id`` narrows the search to one agent, and alone selects that agent's
    first filesystem. A filesystem declared on the AgentOS needs no agent. Any
    other is reachable only through an agent the caller may read, so one that no
    accessible agent holds is not found.
    """
    # An empty agent_id or filesystem_id names nothing.
    agent_id = agent_id or None
    filesystem_id = filesystem_id or None
    if agent_id is None and namespace is None and filesystem_id is None:
        raise HTTPException(status_code=400, detail="Provide a filesystem_id, a namespace or an agent_id")

    selected, declared = await _select_filesystems(os, request, agent_id, namespace, filesystem_id)
    if namespace is None and filesystem_id is None:
        selected = selected[:1]
    if not selected:
        if agent_id is None and filesystem_id is None:
            # A declared filesystem under this name that the caller cannot bind says why.
            unbound = next((e for e in declared if e.filesystem is None and e.forms[0] == namespace), None)
            if unbound is not None:
                raise HTTPException(status_code=400, detail=str(unbound.error))
        # A filesystem the caller cannot reach is indistinguishable from one that does not exist.
        raise HTTPException(status_code=404, detail="Filesystem not found")
    if len(selected) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Several filesystems use this namespace on different backends; "
                "pass filesystem_id or agent_id to choose one"
            ),
        )
    resolved_id, source = selected[0]
    return source.filesystem, sorted(source.agent_ids), resolved_id


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
                if existing.user_id != entry.user_id:
                    # Several users' files share this directory: it has no single owner.
                    existing.user_id = None
    return sorted(directories.values(), key=lambda entry: path_sort_key(entry.path)) + sorted(
        files, key=lambda entry: (path_sort_key(entry.path), entry.user_id or "")
    )


_USER_ID_QUERY = Query(
    None,
    description="User partition to browse: your own, or any user's for an admin. An admin who names none sees every partition",
)
_FILESYSTEM_ID_QUERY = Query(
    None, description="Id of the filesystem to browse, as /config lists it. It needs no namespace or agent_id"
)


async def _list_entries(filesystem: FileSystem, directory: str) -> list[FileSystemEntry]:
    normalized_directory = normalize_directory(directory)
    prefix = f"{normalized_directory}/" if normalized_directory else ""
    directories: Dict[str, FileSystemEntry] = {}
    files: list[FileSystemEntry] = []

    for meta in await filesystem.alist(normalized_directory):
        relative_path = meta.path[len(prefix) :] if prefix and meta.path.startswith(prefix) else meta.path
        name, separator, _ = relative_path.partition("/")
        if separator:
            directory_path = f"{prefix}{name}" if prefix else name
            existing = directories.get(directory_path)
            if existing is None:
                # One listing reads one partition, so every file under the directory shares its owner.
                directories[directory_path] = FileSystemEntry(
                    path=directory_path,
                    type="directory",
                    size_bytes=meta.size_bytes,
                    updated_at=meta.updated_at,
                    user_id=meta.user_id,
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
    os: "AgentOS", request: Request, requested_agent_id: Optional[str], *, required: bool = True
) -> list[str]:
    """The agents whose filesystems the caller may browse.

    A caller who may read no agent is refused, unless ``required`` is False:
    the filesystems declared on the AgentOS are still theirs to browse.
    """
    scopes_are_authoritative = bool(getattr(request.state, "authorization_enabled", False))
    if requested_agent_id:
        if scopes_are_authoritative and not check_resource_access(request, requested_agent_id, "agents", "read"):
            raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail(["agents:read"]))
        return [requested_agent_id]

    accessible_ids = get_accessible_resources(request, "agents") if scopes_are_authoritative else {"*"}
    if not accessible_ids:
        if not required:
            return []
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
    request: Request,
    sources: list[tuple[str, _Source]],
    *,
    query: Optional[str],
) -> list[FileSystemTableEntry]:
    async def _read_files(filesystem_id: str, source: _Source) -> list[FileSystemTableEntry]:
        views = await _apartition_views(source.filesystem, request, None)
        rows: list[FileSystemTableEntry] = []
        for view in views:
            rows.extend(await _read_view(view, filesystem_id, sorted(source.agent_ids)))
        return rows

    async def _read_view(
        filesystem: FileSystem, filesystem_id: str, linked_agent_ids: list[str]
    ) -> list[FileSystemTableEntry]:
        metadata = await filesystem.alist()
        if not query:
            return [
                FileSystemTableEntry(
                    filesystem_id=filesystem_id,
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
                    filesystem_id=filesystem_id,
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
    for start in range(0, len(sources), _MAX_CONCURRENT_FILESYSTEM_READS):
        batch = sources[start : start + _MAX_CONCURRENT_FILESYSTEM_READS]
        results = await asyncio.gather(*(_read_files(filesystem_id, source) for filesystem_id, source in batch))
        for result in results:
            entries.extend(result)

    return sorted(
        entries,
        key=lambda entry: (
            entry.namespace.casefold(),
            path_sort_key(entry.path),
            entry.user_id or "",
            entry.filesystem_id,
            entry.agent_ids,
        ),
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
            "List files across the filesystems visible to the caller: those declared on the AgentOS and "
            "those of the agents the caller may read. Use filesystem_id, agent_id or namespace to narrow "
            "the result, and query to search file contents."
        ),
    )
    async def list_filesystem_files(
        request: Request,
        filesystem_id: Optional[str] = Query(None, description="Filter by filesystem id, as /config lists it"),
        agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
        namespace: Optional[str] = Query(None, description="Filter by resolved namespace"),
        query: Optional[str] = Query(None, min_length=1, max_length=200, description="Search file contents"),
        sort_by: Optional[FileSortField] = _SORT_BY_QUERY,
        sort_order: SortOrder = _SORT_ORDER_QUERY,
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemTableResponse:
        # An empty agent_id or filesystem_id names nothing.
        sources, _ = await _select_filesystems(os, request, agent_id or None, namespace, filesystem_id or None)
        entries = await _get_global_files(request, sources, query=query.strip() if query else None)
        entries = _sort_entries(entries, sort_by, sort_order)
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
        filesystem_id: Optional[str] = _FILESYSTEM_ID_QUERY,
        namespace: Optional[str] = Query(None, description="Resolved namespace of the filesystem to browse"),
        agent_id: Optional[str] = Query(
            None, description="Agent holding the filesystem; alone, selects that agent's first filesystem"
        ),
        directory: str = Query("", description="Relative directory inside the filesystem"),
        sort_by: Optional[FileSortField] = _SORT_BY_QUERY,
        sort_order: SortOrder = _SORT_ORDER_QUERY,
        page: int = Query(1, ge=1, description="1-indexed page number"),
        limit: int = Query(50, ge=1, le=100, description="Page size"),
    ) -> FileSystemListResponse:
        filesystem, holder_ids, resolved_id = await _resolve_filesystem(os, request, agent_id, namespace, filesystem_id)
        # Whose files to list comes from the JWT: an admin sees every partition.
        views = await _apartition_views(filesystem, request, None)
        try:
            normalized_directory = normalize_directory(directory)
            listings = [await _list_entries(view, normalized_directory) for view in views]
            entries = _sort_entries(_merge_entries(listings), sort_by, sort_order)
            usages = [await view.ausage() for view in views]
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        file_count = sum(usage.file_count for usage in usages)
        total_bytes = sum(usage.total_bytes for usage in usages)

        total_count = len(entries)
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        start = (page - 1) * limit
        return FileSystemListResponse(
            filesystem_id=resolved_id,
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
        filesystem_id: Optional[str] = _FILESYSTEM_ID_QUERY,
        namespace: Optional[str] = Query(None, description="Resolved namespace of the filesystem to browse"),
        agent_id: Optional[str] = Query(
            None, description="Agent holding the filesystem; alone, selects that agent's first filesystem"
        ),
        path: str = Query(..., description="Relative file path inside the filesystem"),
        user_id: Optional[str] = _USER_ID_QUERY,
        offset: int = Query(0, ge=0, description="Character offset into the file"),
        limit: int = Query(_MAX_PREVIEW_CHARS, ge=1, le=_MAX_PREVIEW_CHARS, description="Characters to return"),
    ) -> FileSystemContentResponse:
        filesystem, holder_ids, resolved_id = await _resolve_filesystem(os, request, agent_id, namespace, filesystem_id)
        # One file lives in one partition: an admin who names none reads the shared partition.
        filesystem = _partition_views(filesystem, request, user_id)[0]
        try:
            normalized_path = normalize_path(path)
            file_data = await filesystem.aread_with_meta(normalized_path)
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if file_data is None:
            raise HTTPException(status_code=404, detail="File not found")
        metadata = file_data.metadata
        content = file_data.content
        end = min(offset + limit, len(content))
        preview = content[offset:end]
        return FileSystemContentResponse(
            filesystem_id=resolved_id,
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
        filesystem_id: Optional[str] = _FILESYSTEM_ID_QUERY,
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
        filesystem, holder_ids, resolved_id = await _resolve_filesystem(os, request, agent_id, namespace, filesystem_id)
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
            filesystem_id=resolved_id,
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
