"""Explicit sharing of an owned agent session with other users.

A session belongs to its owner (``user_id``). The owner, or an admin, can share it with
named members, recorded under ``SHARING_KEY`` in the session metadata. Members can read the
session and run in it; each run keeps its own author in ``run.user_id``. A session without
an owner is unclaimed: the first identified caller to run in it becomes its owner.
"""

import asyncio
from typing import Any, Dict, Iterable, List, Optional

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.utils import owner_key

SHARING_KEY = "agno_sharing"
MEMBER_JOIN_ATTEMPTS = 5


def _field(session: Any, name: str) -> Any:
    return session.get(name) if isinstance(session, dict) else getattr(session, name, None)


def session_members(session: Any) -> List[str]:
    """User ids the session is shared with, excluding its owner."""
    sharing = (_field(session, "metadata") or {}).get(SHARING_KEY) or {}
    return [str(member) for member in sharing.get("members") or []]


def can_read_session(session: Any, user_id: Optional[str]) -> bool:
    """Whether user_id may read the session: its owner or a member. A caller without a user_id is trusted."""
    owner = _field(session, "user_id")
    if user_id is None or (owner is not None and owner_key(owner) == owner_key(user_id)):
        return True
    return owner is not None and owner_key(user_id) in session_members(session)


def can_run_in_session(session: Any, user_id: Optional[str]) -> bool:
    """Whether user_id may run in the session: a reader, or anyone for an unclaimed session they then claim."""
    return _field(session, "user_id") is None or can_read_session(session, user_id)


def can_share_session(session: Any, user_id: Optional[str], is_admin: bool = False) -> bool:
    """Only the owner or an admin changes who a session is shared with."""
    owner = _field(session, "user_id")
    return is_admin or user_id is None or (owner is not None and owner_key(owner) == owner_key(user_id))


def without_sharing(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Caller-supplied metadata with the sharing key removed; sharing changes only through share_session."""
    if not isinstance(metadata, dict) or SHARING_KEY not in metadata:
        return metadata
    return {key: value for key, value in metadata.items() if key != SHARING_KEY}


def keep_sharing(metadata: Optional[Dict[str, Any]], stored: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """New metadata for a stored session, keeping the stored sharing and ignoring any supplied one."""
    cleaned = dict(without_sharing(metadata) or {})
    if isinstance(stored, dict) and SHARING_KEY in stored:
        cleaned[SHARING_KEY] = stored[SHARING_KEY]
    return cleaned or None


def refresh_sharing(db: BaseDb, session: Any) -> None:
    """Replace the session's sharing with what is stored.

    A run saves the session it loaded, so without this a share or unshare made since would be
    undone by that save. One row read; the runs are not loaded.
    """
    stored = db.get_session(
        session_id=session.session_id, session_type=SessionType.AGENT, deserialize=False, runs_limit=1
    )
    if stored is not None:
        session.metadata = keep_sharing(session.metadata, _field(stored, "metadata"))


async def arefresh_sharing(db: Any, session: Any) -> None:
    """Async refresh_sharing; a sync database is read in place, as the agent's async save path does."""
    if not isinstance(db, AsyncBaseDb):
        refresh_sharing(db, session)
        return
    stored = await db.get_session(
        session_id=session.session_id, session_type=SessionType.AGENT, deserialize=False, runs_limit=1
    )
    if stored is not None:
        session.metadata = keep_sharing(session.metadata, _field(stored, "metadata"))


def _apply_members(session: Any, members: Iterable[str], user_id: Optional[str], is_admin: bool) -> Any:
    if not can_share_session(session, user_id, is_admin):
        raise PermissionError("Only the session owner or an admin can share a session")
    if session.user_id is None:
        # Ownership comes from running in the session, never from sharing it.
        raise ValueError(f"Session {session.session_id} has no owner yet and cannot be shared")
    owner = owner_key(session.user_id)
    unique = list(dict.fromkeys(str(member) for member in members if member is not None and str(member) != owner))
    metadata = dict(session.metadata or {})
    if unique:
        metadata[SHARING_KEY] = {"members": unique}
    else:
        metadata.pop(SHARING_KEY, None)
    session.metadata = metadata or None
    return session


def share_session(
    db: BaseDb,
    session_id: str,
    members: Iterable[str],
    *,
    user_id: Optional[str] = None,
    is_admin: bool = False,
) -> Any:
    """Set the members an agent session is shared with; an empty list unshares it.

    user_id is the acting user, who must own the session unless is_admin is set. Returns the
    updated session.
    """
    session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    if session is None:
        raise ValueError(f"Session {session_id} not found")
    return db.upsert_session(_apply_members(session, members, user_id, is_admin))


async def ashare_session(
    db: Any,
    session_id: str,
    members: Iterable[str],
    *,
    user_id: Optional[str] = None,
    is_admin: bool = False,
) -> Any:
    """Async share_session; accepts a sync or async database, reading a sync one off the event loop."""
    if not isinstance(db, AsyncBaseDb):
        return await asyncio.to_thread(share_session, db, session_id, members, user_id=user_id, is_admin=is_admin)
    session = await db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    if session is None:
        raise ValueError(f"Session {session_id} not found")
    return await db.upsert_session(_apply_members(session, members, user_id, is_admin))


async def aadd_session_member(db: Any, session_id: str, user_id: Optional[str]) -> None:
    """Add user_id as a member of an existing agent session owned by someone else.

    For trusted entry points that scope sessions themselves, such as a chat thread shared by
    everyone in it. A missing or unclaimed session is left alone: the caller's run claims it.
    """
    if db is None or user_id is None:
        return
    # The member list is replaced as a whole, so two senders joining at once can overwrite each
    # other. Re-read after writing and retry until this member is in the stored list.
    for _ in range(MEMBER_JOIN_ATTEMPTS):
        if isinstance(db, AsyncBaseDb):
            session = await db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        else:
            session = await asyncio.to_thread(db.get_session, session_id=session_id, session_type=SessionType.AGENT)
        owner = _field(session, "user_id") if session is not None else None
        if owner is None:
            return
        members = session_members(session)
        if owner_key(owner) == owner_key(user_id) or owner_key(user_id) in members:
            return
        await ashare_session(db, session_id, [*members, user_id], is_admin=True)
    raise RuntimeError(f"Could not add {user_id} to session {session_id}: the member list kept changing")


async def ajoin_shared_session(entity: Any, session_id: str, user_id: Optional[str]) -> None:
    """Add a chat sender as a member of the agent session the chat interface scoped to the thread."""
    from agno.agent import Agent
    from agno.agents.base import BaseExternalAgent
    from agno.utils.log import log_warning

    if not isinstance(entity, (Agent, BaseExternalAgent)):
        return
    try:
        await aadd_session_member(getattr(entity, "db", None), session_id, user_id)
    except Exception as e:
        log_warning(f"Could not add {user_id} to shared session {session_id}: {e}")
