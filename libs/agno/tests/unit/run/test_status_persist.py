"""Unit tests for atomic run-status persistence."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.run.status_persist import apersist_run_status, apersist_run_transition


class FakeAsyncDb:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
        self.calls.append({"session_id": session_id, "run_id": run_id, "fields": fields, "attempt": expected_attempt})
        return self.result


class FakeSyncDb:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
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


class TestFenceFinality:
    """A fence rejection must never be overridden by the unfenced fallback
    (the zombie-clobber path from review)."""

    @pytest.mark.asyncio
    async def test_fenced_rejection_does_not_fall_back(self):
        from agno.run.base import RunStatus
        from agno.run.status_persist import apersist_run_transition

        class FencingDb:
            async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
                return False  # fence rejected: newer attempt owns the row

        saves = []

        class FakeAgent:
            db = FencingDb()

        class FakeRun:
            run_id = "r1"
            status = RunStatus.error

        import agno.agent._session as sess_mod

        original = sess_mod.asave_session

        async def spy_save(component, session=None, **kw):
            saves.append(session)

        sess_mod.asave_session = spy_save
        try:
            await apersist_run_transition(FakeAgent(), "agent", "s1", FakeRun(), expected_attempt=1)
        finally:
            sess_mod.asave_session = original
        assert saves == [], "fenced-out writer must not clobber via the whole-session fallback"

    @pytest.mark.asyncio
    async def test_unfenced_missing_run_still_falls_back(self):
        from agno.run.status_persist import apersist_run_status, fallback_allowed

        class NoRowDb:
            async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
                return False  # run not in session yet

        class FakeAgent:
            db = NoRowDb()

        result = await apersist_run_status(FakeAgent(), "agent", "s1", "r1", {"status": "error"})
        assert result is False
        assert fallback_allowed(result, None) is True, "no fence requested: fallback creates the run"
        assert fallback_allowed(result, 1) is False, "fence requested: False is final"

    @pytest.mark.asyncio
    async def test_no_adapter_support_falls_back(self):
        from agno.run.status_persist import apersist_run_status, fallback_allowed

        class BareDb:
            pass

        class FakeAgent:
            db = BareDb()

        result = await apersist_run_status(FakeAgent(), "agent", "s1", "r1", {"status": "error"})
        assert result is None
        assert fallback_allowed(result, 1) is True, "no atomic primitive: fallback is the only option"


class TestGenerationStamping:
    @pytest.mark.asyncio
    async def test_stamped_generation_fences_zombie(self):
        """Attempt 2 stamps queue_attempt=2 at claim; attempt 1's late ERROR
        write (expected_attempt=1) must be rejected, not stamped vacuously."""
        from agno.run.base import RunStatus
        from agno.run.status_persist import apersist_run_status, fallback_allowed

        stored = {"queue_attempt": None, "status": "running"}

        class Db:
            async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
                if (
                    expected_attempt is not None
                    and stored["queue_attempt"] is not None
                    and stored["queue_attempt"] > expected_attempt
                ):
                    return False
                stored.update(fields)
                if expected_attempt is not None:
                    stored["queue_attempt"] = expected_attempt
                return True

        class FakeAgent:
            db = Db()

        # Attempt 2 claims and stamps
        r = await apersist_run_status(FakeAgent(), "agent", "s1", "r1", {"queue_attempt": 2}, expected_attempt=2)
        assert r is True and stored["queue_attempt"] == 2

        # Attempt 1's zombie tries its terminal write
        r = await apersist_run_status(
            FakeAgent(), "agent", "s1", "r1", {"status": RunStatus.error.value}, expected_attempt=1
        )
        assert r is False, "zombie must be fenced by the stamped generation"
        assert fallback_allowed(r, 1) is False
        assert stored["status"] == "running", "zombie write must not land"


class TestPreparedRunSerializes:
    def test_prepared_agent_run_round_trips(self):
        """The PENDING row aprepare builds must survive to_dict: a raw-string
        input made it raise inside the session save, so the row never landed
        (pollers 404'd and the attempt stamp found no run)."""
        from agno.run.agent import RunInput, RunOutput
        from agno.run.base import RunStatus

        run = RunOutput(run_id="r1", session_id="s1", input=RunInput(input_content="hello"), status=RunStatus.pending)
        d = run.to_dict()
        assert d["input"]["input_content"] == "hello"
        assert RunOutput.from_dict(d).run_id == "r1"

    def test_prepared_team_run_round_trips(self):
        from agno.run.base import RunStatus
        from agno.run.team import TeamRunInput, TeamRunOutput

        run = TeamRunOutput(
            run_id="r1", session_id="s1", input=TeamRunInput(input_content="hello"), status=RunStatus.pending
        )
        d = run.to_dict()
        assert d["input"]["input_content"] == "hello"
