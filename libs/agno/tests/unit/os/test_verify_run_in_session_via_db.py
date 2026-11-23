"""Unit tests for verify_run_in_session_via_db.

Used by factory cancel routes — those routes don't resolve a factory instance,
so the helper checks run ownership directly via the OS db.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.middleware.user_scope import verify_run_in_session_via_db


def _make_session(run_id: str | None):
    """Build a session-like object with a get_run method."""
    session = MagicMock()
    session.get_run = MagicMock(return_value=MagicMock() if run_id else None)
    return session


@pytest.mark.asyncio
async def test_raises_404_when_db_is_none():
    with pytest.raises(HTTPException) as exc:
        await verify_run_in_session_via_db(None, "sess", "run", "user-a")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_sync_db_session_not_found_raises_404():
    db = MagicMock(spec=BaseDb)
    db.get_session = MagicMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await verify_run_in_session_via_db(db, "sess", "run", "user-a")
    assert exc.value.status_code == 404
    db.get_session.assert_called_once_with(session_id="sess", user_id="user-a")


@pytest.mark.asyncio
async def test_async_db_session_not_found_raises_404():
    db = MagicMock(spec=AsyncBaseDb)
    db.get_session = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await verify_run_in_session_via_db(db, "sess", "run", "user-a")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_session_owned_but_run_missing_raises_404():
    db = MagicMock(spec=BaseDb)
    db.get_session = MagicMock(return_value=_make_session(run_id=None))

    with pytest.raises(HTTPException) as exc:
        await verify_run_in_session_via_db(db, "sess", "run", "user-a")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_run_owned_by_user_passes():
    session = _make_session(run_id="run-1")
    db = MagicMock(spec=BaseDb)
    db.get_session = MagicMock(return_value=session)

    # Should not raise
    await verify_run_in_session_via_db(db, "sess", "run-1", "user-a")
    session.get_run.assert_called_once_with(run_id="run-1")


@pytest.mark.asyncio
async def test_async_run_owned_by_user_passes():
    session = _make_session(run_id="run-1")
    db = MagicMock(spec=AsyncBaseDb)
    db.get_session = AsyncMock(return_value=session)

    await verify_run_in_session_via_db(db, "sess", "run-1", "user-a")


@pytest.mark.asyncio
async def test_session_without_get_run_raises_404():
    """Defensive: if the returned object can't enumerate runs, fail closed."""
    db = MagicMock(spec=BaseDb)
    # Use a plain object instead of MagicMock so `getattr(...,  None)` returns None
    db.get_session = MagicMock(return_value=object())

    with pytest.raises(HTTPException) as exc:
        await verify_run_in_session_via_db(db, "sess", "run", "user-a")
    assert exc.value.status_code == 404
