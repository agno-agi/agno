from __future__ import annotations

import asyncio
import time
from typing import Any, Literal, NamedTuple, Optional, Type

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

EntityType = Literal["agent", "team", "workflow"]

_SESSION_DISPATCH: dict[str, tuple[SessionType, Type[Any], str]] = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


class _SessionStoreConfig(NamedTuple):
    session_type: SessionType
    session_cls: Type[Any]
    id_field: str
    db: Any
    has_db: bool
    is_async_db: bool


def build_session_store_config(entity: object, entity_type: str) -> _SessionStoreConfig:
    session_type, session_cls, id_field = _SESSION_DISPATCH[entity_type]
    db = getattr(entity, "db", None)
    return _SessionStoreConfig(
        session_type=session_type,
        session_cls=session_cls,
        id_field=id_field,
        db=db,
        has_db=isinstance(db, (BaseDb, AsyncBaseDb)),
        is_async_db=isinstance(db, AsyncBaseDb),
    )


async def find_latest_session_id(
    cfg: _SessionStoreConfig,
    user_id: Optional[str],
    entity_id: Optional[str],
    session_scope: Optional[str] = None,
) -> Optional[str]:
    # DB has no session_id prefix filter, so fetch recent sessions and match client-side
    query = dict(
        session_type=cfg.session_type,
        user_id=user_id,
        component_id=entity_id,
        sort_by="created_at",
        sort_order="desc",
        limit=50,
        deserialize=False,
    )
    if cfg.is_async_db:
        results = await cfg.db.get_sessions(**query)  # type: ignore[arg-type, misc]
    else:
        results = await asyncio.to_thread(cfg.db.get_sessions, **query)  # type: ignore[arg-type]
    rows = results[0] if isinstance(results, tuple) else results
    if not rows:
        return None
    for row in rows:
        sid = row.get("session_id", "") if isinstance(row, dict) else getattr(row, "session_id", "")
        if session_scope and sid and sid.startswith(session_scope):
            return sid
    return None


async def insert_sentinel_session(
    cfg: _SessionStoreConfig,
    session_id: str,
    user_id: Optional[str],
    entity_id: Optional[str],
) -> None:
    """Write a minimal session row so find_latest_session_id picks it up next."""
    now = int(time.time())
    kwargs: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
    }
    if entity_id:
        kwargs[cfg.id_field] = entity_id
    session = cfg.session_cls(**kwargs)
    if cfg.is_async_db:
        await cfg.db.upsert_session(session, deserialize=False)
    else:
        await asyncio.to_thread(cfg.db.upsert_session, session, deserialize=False)
