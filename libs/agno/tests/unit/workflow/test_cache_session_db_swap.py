"""Regression tests: with ``cache_session=True`` the cached session must not survive
a reassignment of ``workflow.db``.

Sibling of ``tests/unit/agent/test_cache_session_db_swap.py`` — Workflow caches its
session in ``_workflow_session`` and had the same hazard: after ``workflow.db`` was
pointed at a fresh database, ``read_or_create_session`` kept serving the session
loaded from the old database.
"""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.workflow.workflow import Workflow


def _make_workflow(**kwargs) -> Workflow:
    return Workflow(name="test-workflow", steps=[], cache_session=True, **kwargs)


class TestWorkflowCacheHitWithinOneDb:
    def test_second_read_reuses_cached_session_object(self):
        workflow = _make_workflow(db=InMemoryDb())

        first = workflow.read_or_create_session(session_id="conv")
        assert workflow.read_or_create_session(session_id="conv") is first

    @pytest.mark.asyncio
    async def test_second_read_reuses_cached_session_object_async(self):
        workflow = _make_workflow(db=InMemoryDb())

        first = await workflow.aread_or_create_session(session_id="conv")
        assert await workflow.aread_or_create_session(session_id="conv") is first


class TestWorkflowDbSwapInvalidation:
    def test_db_swap_drops_cached_session(self):
        workflow = _make_workflow(db=InMemoryDb())
        old_session = workflow.read_or_create_session(session_id="conv")

        workflow.db = InMemoryDb()
        new_session = workflow.read_or_create_session(session_id="conv")

        assert new_session is not old_session

    @pytest.mark.asyncio
    async def test_db_swap_drops_cached_session_async(self):
        workflow = _make_workflow(db=InMemoryDb())
        old_session = await workflow.aread_or_create_session(session_id="conv")

        workflow.db = InMemoryDb()
        new_session = await workflow.aread_or_create_session(session_id="conv")

        assert new_session is not old_session


class TestWorkflowSessionIdSwitch:
    def test_session_id_switch_does_not_serve_stale_cache(self):
        workflow = _make_workflow(db=InMemoryDb())

        session_a = workflow.read_or_create_session(session_id="conv-a")
        session_b = workflow.read_or_create_session(session_id="conv-b")

        assert session_b is not session_a
        assert session_b.session_id == "conv-b"
