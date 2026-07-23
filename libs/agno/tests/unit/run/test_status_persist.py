"""Unit tests for atomic run-status persistence."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.run.status_persist import apersist_run_status, apersist_run_transition


class FakeAsyncDb:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None):
        self.calls.append({"session_id": session_id, "run_id": run_id, "fields": fields, "attempt": expected_attempt})
        return self.result


class FakeSyncDb:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None):
        self.calls.append({"fields": fields, "attempt": expected_attempt})
        return self.result


class TestApersistRunStatus:
    @pytest.mark.asyncio
    async def test_async_adapter_called_with_fencing(self):
        component = MagicMock()
        component.db = FakeAsyncDb()
        assert await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"}, expected_attempt=2)
        assert component.db.calls[0]["attempt"] == 2
        assert component.db.calls[0]["fields"] == {"status": "ERROR"}

    @pytest.mark.asyncio
    async def test_sync_adapter_runs_in_thread(self):
        component = MagicMock()
        component.db = FakeSyncDb()
        assert await apersist_run_status(component, "agent", "s1", "r1", {"status": "CANCELLED"})
        assert component.db.calls[0]["fields"] == {"status": "CANCELLED"}

    @pytest.mark.asyncio
    async def test_no_primitive_returns_false(self):
        component = MagicMock()
        component.db = object()  # no update_run_in_session
        assert not await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"})

    @pytest.mark.asyncio
    async def test_rejected_write_returns_false(self):
        component = MagicMock()
        component.db = FakeAsyncDb(result=False)
        assert not await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"}, expected_attempt=1)


class TestApersistRunTransition:
    @pytest.mark.asyncio
    async def test_atomic_path_skips_fallback(self, monkeypatch):
        component = MagicMock()
        component.db = FakeAsyncDb()
        run_response = MagicMock()
        run_response.run_id = "r1"
        run_response.status = MagicMock(value="RUNNING")

        fallback = AsyncMock()
        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fallback)
        await apersist_run_transition(component, "agent", "s1", run_response)
        assert component.db.calls[0]["fields"]["status"] == "RUNNING"
        fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_extra_fields_included(self):
        component = MagicMock()
        component.db = FakeAsyncDb()
        run_response = MagicMock()
        run_response.run_id = "r1"
        run_response.status = MagicMock(value="ERROR")
        await apersist_run_transition(
            component, "workflow", "s1", run_response, extra_fields={"content": "failed: boom"}
        )
        assert component.db.calls[0]["fields"] == {"status": "ERROR", "content": "failed: boom"}
