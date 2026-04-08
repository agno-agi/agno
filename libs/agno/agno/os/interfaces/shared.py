from __future__ import annotations

import asyncio
import os
from typing import Any, List, NamedTuple, Optional, Type

from agno.agent import RunEvent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

# =============================================================================
# Event Normalization
# =============================================================================


def normalize_event(event: str) -> str:
    """Strip 'Team' prefix so agent and team events use the same handlers."""
    return event.removeprefix("Team")


# Workflows orchestrate multiple agents via steps/loops/conditions. Without
# suppression, each inner agent's tool calls and reasoning events would flood
# the stream with low-level noise. We only show step-level progress.
# Values are NORMALIZED (no "Team" prefix) so one set covers agent + team events.
SUPPRESSED_IN_WORKFLOW: frozenset[str] = frozenset(
    {
        RunEvent.reasoning_started.value,
        RunEvent.reasoning_completed.value,
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.tool_call_error.value,
        RunEvent.memory_update_started.value,
        RunEvent.memory_update_completed.value,
        RunEvent.run_content.value,
        RunEvent.run_intermediate_content.value,
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    }
)


# =============================================================================
# Team Member Helpers
# =============================================================================


def member_name(chunk: Any, entity_name: str) -> Optional[str]:
    # Return name only for team members (not leader) to prefix task card
    # labels like "Researcher: web_search" for disambiguation
    name = getattr(chunk, "agent_name", None)
    if name and isinstance(name, str) and name != entity_name:
        return name
    return None


def task_id(agent_name: Optional[str], base_id: str) -> str:
    # Prefix card IDs per agent so concurrent tool calls from different
    # team members don't collide in the stream
    if agent_name:
        safe = agent_name.lower().replace(" ", "_")[:20]
        return f"{safe}_{base_id}"
    return base_id


# =============================================================================
# Text Chunking
# =============================================================================


def chunk_text(text: str, max_len: int) -> List[str]:
    # Split on natural boundaries: paragraph > line > word > hard cut
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        cut = remaining.rfind("\n\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len

        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    return chunks


# =============================================================================
# Media Collection
# =============================================================================


def collect_media_from_chunk(state: Any, chunk: Any) -> None:
    # Shared dedup logic for accumulating media from streaming events.
    # State must have images, videos, audio, files list attributes.
    for img in getattr(chunk, "images", None) or []:
        if img not in state.images:
            state.images.append(img)
    for vid in getattr(chunk, "videos", None) or []:
        if vid not in state.videos:
            state.videos.append(vid)
    for aud in getattr(chunk, "audio", None) or []:
        if aud not in state.audio:
            state.audio.append(aud)
    for f in getattr(chunk, "files", None) or []:
        if f not in state.files:
            state.files.append(f)


# =============================================================================
# Session Store Config
# =============================================================================

_SESSION_DISPATCH = {
    "agent": (SessionType.AGENT, AgentSession, "agent_id"),
    "team": (SessionType.TEAM, TeamSession, "team_id"),
    "workflow": (SessionType.WORKFLOW, WorkflowSession, "workflow_id"),
}


class SessionStoreConfig(NamedTuple):
    session_type: SessionType
    session_cls: Type[Any]
    id_field: str
    db: Any
    has_db: bool
    is_async_db: bool


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


# =============================================================================
# Dev Mode Check
# =============================================================================


def is_dev_mode() -> bool:
    return os.getenv("APP_ENV", "").lower() == "development"
