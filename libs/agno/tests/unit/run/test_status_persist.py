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


class TestWorkflowCheckpoint:
    class _Step:
        def __init__(self, name):
            self.name = name

        def to_dict(self):
            return {"step_name": self.name, "content": "done"}

    @pytest.mark.asyncio
    async def test_checkpoint_patches_step_results(self):
        from agno.run.status_persist import apersist_workflow_checkpoint

        workflow = MagicMock()
        workflow.db = FakeAsyncDb()
        await apersist_workflow_checkpoint(workflow, "s1", "r1", [self._Step("a"), self._Step("b")])
        fields = workflow.db.calls[0]["fields"]
        assert fields["status"] == "RUNNING"
        assert [s["step_name"] for s in fields["step_results"]] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_checkpoint_skips_without_primitive(self):
        from agno.run.status_persist import apersist_workflow_checkpoint

        workflow = MagicMock()
        workflow.db = object()
        await apersist_workflow_checkpoint(workflow, "s1", "r1", [self._Step("a")])  # no raise

    def test_sync_checkpoint_uses_sync_adapter_only(self):
        from agno.run.status_persist import persist_workflow_checkpoint

        workflow = MagicMock()
        workflow.db = FakeSyncDb()
        persist_workflow_checkpoint(workflow, "s1", "r1", [self._Step("a")])
        assert workflow.db.calls[0]["fields"]["status"] == "RUNNING"

        workflow_async = MagicMock()
        workflow_async.db = FakeAsyncDb()
        persist_workflow_checkpoint(workflow_async, "s1", "r1", [self._Step("a")])
        assert workflow_async.db.calls == []  # cannot await from sync loop: skip
