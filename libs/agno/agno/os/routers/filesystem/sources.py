"""Authorized browser sources and bounded views of published Knowledge pages."""

import hashlib
import json
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException, Request

from agno.agent import Agent
from agno.agent.agent import get_agents
from agno.db.base import BaseDb
from agno.fs._paths import path_sort_key
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page.filesystem import PageFileSystem
from agno.knowledge.page.types import PageChanged, PageError, PageNotFound
from agno.os.auth import check_resource_access
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.filesystem.schema import FileSource, FileSourceEntry
from agno.os.schema import PaginationInfo
from agno.os.scopes import has_required_scopes

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def _can_read(request: Request, kind: str, resource_id: str = "") -> bool:
    if not getattr(request.state, "authorization_enabled", False):
        return True
    if kind == "agent":
        return check_resource_access(request, resource_id, "agents", "read")
    admin_scope = getattr(request.state, "admin_scope", None)
    return has_required_scopes(
        getattr(request.state, "scopes", []),
        ["knowledge:read"],
        admin_scope=admin_scope if isinstance(admin_scope, str) else None,
    )


def _knowledge_sources(os: "AgentOS") -> dict[str, Knowledge]:
    sources: dict[str, Knowledge] = {}
    # Only instances explicitly exposed by AgentOS discovery are browsable.
    # Do not enumerate database namespaces or inspect arbitrary tool closures.
    for knowledge in os.knowledge_instances or []:
        if not isinstance(knowledge, Knowledge) or knowledge.page_store is None:
            continue
        db = knowledge.contents_db
        identity = json.dumps(
            [
                getattr(db, "id", None),
                getattr(db, "knowledge_table_name", None),
                knowledge.name,
                knowledge.page_store.namespace,
            ]
        )
        source_id = "knowledge:" + hashlib.sha256(identity.encode()).hexdigest()
        sources[source_id] = knowledge
    return sources


def _list_sources(os: "AgentOS", request: Request) -> list[FileSource]:
    agents = list(os.agents or [])
    if isinstance(os.db, BaseDb):
        agents.extend(
            get_agents(
                db=os.db,
                registry=os.registry,
                exclude_component_ids={agent.id for agent in agents if agent.id is not None} or None,
                user_id=get_scoped_user_id(request),
            )
            or []
        )
    sources = [
        FileSource(id=f"agent:{agent.id}", name=agent.name or agent.id, kind="agent", agent_id=agent.id)
        for agent in agents
        if isinstance(agent, Agent)
        and agent.id is not None
        and agent.filesystem
        and not isinstance(agent.filesystem, PageFileSystem)
        and _can_read(request, "agent", agent.id)
    ]
    if _can_read(request, "knowledge"):
        sources.extend(
            FileSource(id=source_id, name=knowledge.name or "Knowledge pages", kind="knowledge")
            for source_id, knowledge in _knowledge_sources(os).items()
        )
    return sources


def _resolve_source(os: "AgentOS", request: Request, source_id: str) -> tuple[Optional[str], Optional[Knowledge]]:
    if source_id.startswith("agent:"):
        agent_id = source_id.removeprefix("agent:")
        if not agent_id or not _can_read(request, "agent", agent_id):
            raise HTTPException(status_code=404, detail="File source not found")
        # The existing agent resolver enforces ownership and filesystem isolation.
        return agent_id, None
    if not _can_read(request, "knowledge"):
        raise HTTPException(status_code=404, detail="File source not found")
    knowledge = _knowledge_sources(os).get(source_id)
    if knowledge is None:
        raise HTTPException(status_code=404, detail="File source not found")
    return None, knowledge


def _pagination(count: int, page: int, limit: int) -> PaginationInfo:
    return PaginationInfo(page=page, limit=limit, total_count=count, total_pages=(count + limit - 1) // limit)


def _page_error(error: PageError) -> HTTPException:
    status = 404 if isinstance(error, PageNotFound) else 409 if isinstance(error, PageChanged) else 503
    detail = {"code": error.code}
    if isinstance(error, PageChanged) and error.current_revision:
        detail["current_revision"] = error.current_revision
    return HTTPException(status_code=status, detail=detail)


async def _page_entries(knowledge: Knowledge, directory: str) -> list[FileSourceEntry]:
    prefix = f"/{directory}/" if directory else "/"
    entries: dict[str, FileSourceEntry] = {}
    cursor = None
    # The browser uses numbered directory pagination. Bound catalog aggregation
    # and fail explicitly rather than presenting an incomplete directory as complete.
    for _ in range(50):
        result = await knowledge.alist_pages(prefix=prefix, cursor=cursor, limit=200)
        if result.restart_required:
            raise HTTPException(status_code=409, detail="Knowledge changed. Refresh the directory.")
        for item in result.pages:
            if not item.path.startswith(prefix):
                continue
            relative = item.path[len(prefix) :]
            name, separator, _ = relative.partition("/")
            path = f"{directory}/{name}" if directory else name
            entries[path] = (
                FileSourceEntry(path=path, type="directory")
                if separator
                else FileSourceEntry(path=path, type="file", title=item.title, url=item.url, revision=item.revision)
            )
        cursor = result.next_cursor
        if cursor is None:
            return sorted(entries.values(), key=lambda entry: (entry.type != "directory", path_sort_key(entry.path)))
    raise HTTPException(status_code=413, detail="Directory is too large. Browse a narrower path.")
