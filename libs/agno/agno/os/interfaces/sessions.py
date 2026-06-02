from __future__ import annotations

import asyncio
from typing import Any, NamedTuple, Optional, Type

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

# (session_type, session_class, entity_id_attribute_name) per entity kind
_SESSION_DISPATCH = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


class SessionStoreConfig(NamedTuple):
    session_type: SessionType
    session_cls: Type[Any]
    id_field: str  # Attribute name on the entity holding its own ID (e.g. "agent_id")
    db: Any
    has_db: bool  # True when db is a BaseDb or AsyncBaseDb instance
    is_async_db: bool  # True for AsyncBaseDb — drives await vs to_thread dispatch


def build_session_store_config(entity: object, entity_type: str) -> SessionStoreConfig:
    session_type, session_cls, id_field = _SESSION_DISPATCH[entity_type]
    db = getattr(entity, "db", None)
    return SessionStoreConfig(
        session_type=session_type,
        session_cls=session_cls,
        id_field=id_field,
        db=db,
        has_db=isinstance(db, (BaseDb, AsyncBaseDb)),
        is_async_db=isinstance(db, AsyncBaseDb),
    )


async def find_latest_session_id(
    cfg: SessionStoreConfig,
    user_id: Optional[str],
    entity_id: Optional[str],
    session_scope: Optional[str] = None,
) -> Optional[str]:
    # DB API has no session_id prefix filter; fetch recent sessions
    # and filter client-side to match the chat/thread/topic scope
    query = dict(
        session_type=cfg.session_type,
        user_id=user_id,
        component_id=entity_id,
        sort_by="created_at",
        sort_order="desc",
        limit=50,
        deserialize=False,  # Raw dicts — avoid constructing full session objects just to read session_id
    )
    if cfg.is_async_db:
        results = await cfg.db.get_sessions(**query)  # type: ignore[arg-type, misc]
    else:
        results = await asyncio.to_thread(cfg.db.get_sessions, **query)  # type: ignore[arg-type]
    # Some DB implementations return (rows, total_count) tuple; extract just the rows
    rows = results[0] if isinstance(results, tuple) else results
    if not rows:
        return None
    for row in rows:
        sid = row.get("session_id", "") if isinstance(row, dict) else getattr(row, "session_id", "")
        if session_scope and sid and sid.startswith(session_scope):
            return sid
    return None
