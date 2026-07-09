"""Tests for paginated session runs retrieval (#8805).

GET /sessions/{id}/runs (and the MCP get_session_runs tool) previously returned
the entire runs array for a session — painful for long transcripts. These tests
cover the new offset/limit pagination that returns a page plus a total count,
while the default (no pagination) behavior is unchanged.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from agno.db.base import BaseDb, SessionType
from agno.os.services.sessions import (
    SessionNotFoundError,
    get_session_runs,
    get_session_runs_page,
)


def _make_run(run_id: str, created_at: int) -> Dict[str, Any]:
    return {"run_id": run_id, "agent_id": "a", "created_at": created_at, "messages": []}


def _make_session(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"session_id": "s1", "agent_id": "a", "runs": runs}


def _mock_db(session: Optional[Dict[str, Any]]) -> BaseDb:
    db = MagicMock(spec=BaseDb)
    db.get_session.return_value = session
    return db


SESSION_RUNS = [
    _make_run("r1", 1000),
    _make_run("r2", 2000),
    _make_run("r3", 3000),
    _make_run("r4", 4000),
    _make_run("r5", 5000),
]


# --- default behavior unchanged (get_session_runs) ---


@pytest.mark.asyncio
async def test_get_session_runs_returns_all_by_default():
    db = _mock_db(_make_session(SESSION_RUNS))
    runs = await get_session_runs(db, session_id="s1", session_type=SessionType.AGENT)
    assert [r.run_id for r in runs] == ["r1", "r2", "r3", "r4", "r5"]


@pytest.mark.asyncio
async def test_get_session_runs_raises_when_session_missing():
    db = _mock_db(None)
    with pytest.raises(SessionNotFoundError):
        await get_session_runs(db, session_id="missing", session_type=SessionType.AGENT)


# --- paginated page (get_session_runs_page) ---


@pytest.mark.asyncio
async def test_page_returns_page_and_total_count():
    db = _mock_db(_make_session(SESSION_RUNS))
    page, total = await get_session_runs_page(db, session_id="s1", session_type=SessionType.AGENT, limit=2, offset=0)
    assert total == 5
    assert [r.run_id for r in page] == ["r1", "r2"]


@pytest.mark.asyncio
async def test_page_offset_advances():
    db = _mock_db(_make_session(SESSION_RUNS))
    page, total = await get_session_runs_page(db, session_id="s1", session_type=SessionType.AGENT, limit=2, offset=2)
    assert total == 5
    assert [r.run_id for r in page] == ["r3", "r4"]


@pytest.mark.asyncio
async def test_page_last_partial_page():
    db = _mock_db(_make_session(SESSION_RUNS))
    page, total = await get_session_runs_page(db, session_id="s1", session_type=SessionType.AGENT, limit=2, offset=4)
    assert total == 5
    assert [r.run_id for r in page] == ["r5"]


@pytest.mark.asyncio
async def test_page_beyond_end_is_empty_with_correct_total():
    db = _mock_db(_make_session(SESSION_RUNS))
    page, total = await get_session_runs_page(db, session_id="s1", session_type=SessionType.AGENT, limit=2, offset=10)
    assert total == 5
    assert page == []


@pytest.mark.asyncio
async def test_page_applies_timestamp_filter_before_pagination():
    """created_after/bcreated_before filter the universe before limit/offset apply."""
    db = _mock_db(_make_session(SESSION_RUNS))
    page, total = await get_session_runs_page(
        db, session_id="s1", session_type=SessionType.AGENT, limit=10, offset=0, created_after=2500
    )
    # Only r3, r4, r5 survive the filter.
    assert total == 3
    assert [r.run_id for r in page] == ["r3", "r4", "r5"]


@pytest.mark.asyncio
async def test_page_default_limit_returns_all():
    db = _mock_db(_make_session(SESSION_RUNS))
    page, total = await get_session_runs_page(db, session_id="s1", session_type=SessionType.AGENT)
    assert total == 5
    assert len(page) == 5


@pytest.mark.asyncio
async def test_page_raises_when_session_missing():
    db = _mock_db(None)
    with pytest.raises(SessionNotFoundError):
        await get_session_runs_page(db, session_id="missing", session_type=SessionType.AGENT, limit=2, offset=0)
