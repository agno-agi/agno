"""Unit tests for atomic run-status persistence (typed outcomes)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.run.base import RunStatus
from agno.run.status_persist import (
    RunPersistOutcome,
    apersist_run_status,
    apersist_run_transition,
    fallback_allowed,
)


class FakeAsyncDb:
    """Legacy bool-returning adapter (the third-party shape)."""

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


class GuardedFakeDb:
    """Typed-outcome adapter mimicking the Postgres primitive's guards over
    one in-memory row: attempt fence, terminal-row refusal, missing row."""

    def __init__(self, row=None):
        self.row = row

    async def update_run_in_session(
        self, session_id, run_id, fields, expected_attempt=None, user_id=None, content_if_absent=None
    ):
        if self.row is None or self.row.get("run_id") != run_id:
            return RunPersistOutcome.MISSING
        stored_attempt = self.row.get("queue_attempt")
        if expected_attempt is not None and stored_attempt is not None and stored_attempt > expected_attempt:
            return RunPersistOutcome.STALE_ATTEMPT
        stored_status = str(self.row.get("status") or "").lower()
        incoming = str(fields.get("status") or "").lower()
        if stored_status in ("completed", "cancelled") and incoming and incoming != stored_status:
            return RunPersistOutcome.TERMINAL_REFUSED
        self.row.update(fields)
        if expected_attempt is not None:
            self.row["queue_attempt"] = expected_attempt
        return RunPersistOutcome.UPDATED


class TestApersistRunStatus:
    @pytest.mark.asyncio
    async def test_async_adapter_called_with_fencing(self):
        component = MagicMock()
        component.db = FakeAsyncDb()
        result = await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"}, expected_attempt=2)
        assert result is RunPersistOutcome.UPDATED
        assert component.db.calls[0]["attempt"] == 2
        assert component.db.calls[0]["fields"] == {"status": "ERROR"}

    @pytest.mark.asyncio
    async def test_sync_adapter_runs_in_thread(self):
        component = MagicMock()
        component.db = FakeSyncDb()
        result = await apersist_run_status(component, "agent", "s1", "r1", {"status": "CANCELLED"})
        assert result is RunPersistOutcome.UPDATED
        assert component.db.calls[0]["fields"] == {"status": "CANCELLED"}

    @pytest.mark.asyncio
    async def test_no_primitive_returns_unavailable(self):
        component = MagicMock()
        component.db = object()  # no update_run_in_session
        result = await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"})
        assert result is RunPersistOutcome.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_legacy_bool_false_maps_to_old_semantics(self):
        """Third-party bool adapters keep the historical decisions: a fenced
        False was fence-final (STALE_ATTEMPT), an unfenced False meant the
        row does not exist yet (MISSING)."""
        component = MagicMock()
        component.db = FakeAsyncDb(result=False)
        fenced = await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"}, expected_attempt=1)
        assert fenced is RunPersistOutcome.STALE_ATTEMPT
        unfenced = await apersist_run_status(component, "agent", "s1", "r1", {"status": "ERROR"})
        assert unfenced is RunPersistOutcome.MISSING

    @pytest.mark.asyncio
    async def test_typed_outcome_passes_through(self):
        component = MagicMock()
        component.db = GuardedFakeDb(row={"run_id": "r1", "status": "running"})
        result = await apersist_run_status(component, "agent", "s1", "r1", {"status": "error"})
        assert result is RunPersistOutcome.UPDATED
        assert component.db.row["status"] == "error"


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


class TestTypedOutcomeFinality:
    """The review contract: fallback only on MISSING/UNAVAILABLE; never after
    STALE_ATTEMPT or TERMINAL_REFUSED; DB exceptions surface as exceptions."""

    def _forbid_fallback(self, monkeypatch):
        async def forbidden(component, session_id=None, user_id=None):
            raise AssertionError("the whole-session fallback must not run")

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", forbidden)

    @pytest.mark.asyncio
    async def test_completed_row_survives_cancelled_write(self, monkeypatch):
        """COMPLETED + late CANCELLED write -> stays COMPLETED. Previously the
        primitive's ambiguous False sent the unfenced whole-session fallback
        (which has no terminal guard) to clobber the row."""
        self._forbid_fallback(monkeypatch)
        db = GuardedFakeDb(row={"run_id": "r1", "status": RunStatus.completed.value})
        component = SimpleNamespace(db=db)
        run = SimpleNamespace(run_id="r1", status=RunStatus.cancelled)
        await apersist_run_transition(component, "agent", "s1", run)
        assert db.row["status"] == RunStatus.completed.value

    @pytest.mark.asyncio
    async def test_cancelled_row_survives_error_write(self, monkeypatch):
        self._forbid_fallback(monkeypatch)
        db = GuardedFakeDb(row={"run_id": "r1", "status": RunStatus.cancelled.value})
        component = SimpleNamespace(db=db)
        run = SimpleNamespace(run_id="r1", status=RunStatus.error)
        await apersist_run_transition(component, "agent", "s1", run)
        assert db.row["status"] == RunStatus.cancelled.value

    @pytest.mark.asyncio
    async def test_missing_row_still_creatable_via_fallback(self, monkeypatch):
        """MISSING is not final: the fallback's create-and-save path is the
        legitimate creator of a row the primitive could not find."""
        saves = []
        upserts = []

        async def fake_read(component, session_id=None, user_id=None):
            return SimpleNamespace(upsert_run=lambda run=None: upserts.append(run))

        async def fake_save(component, session=None):
            saves.append(session)

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_save)

        async def fake_save_run(component, run=None, session_id=None, user_id=None, run_index=None):
            saves.append(("run", getattr(run, "run_id", None)))

        monkeypatch.setattr("agno.agent._session.asave_run", fake_save_run)
        db = GuardedFakeDb(row=None)
        component = SimpleNamespace(db=db)
        run = SimpleNamespace(run_id="r1", status=RunStatus.error)
        await apersist_run_transition(component, "agent", "s1", run)
        # v3 substrate: the fallback persists the run (asave_run) AND the session row
        assert upserts == [run] and len(saves) == 2

    @pytest.mark.asyncio
    async def test_older_attempt_never_reaches_fallback(self, monkeypatch):
        self._forbid_fallback(monkeypatch)
        db = GuardedFakeDb(row={"run_id": "r1", "status": "running", "queue_attempt": 2})
        component = SimpleNamespace(db=db)
        run = SimpleNamespace(run_id="r1", status=RunStatus.error)
        await apersist_run_transition(component, "agent", "s1", run, expected_attempt=1)
        assert db.row["status"] == "running", "attempt 1's late write must not land anywhere"

    @pytest.mark.asyncio
    async def test_db_exception_propagates_without_fallback(self, monkeypatch):
        """A DB failure must surface as a failure - never collapse into an
        outcome that re-opens the unfenced fallback mid-outage."""
        self._forbid_fallback(monkeypatch)

        class RaisingDb:
            async def update_run_in_session(self, *a, **kw):
                raise RuntimeError("db down")

        component = SimpleNamespace(db=RaisingDb())
        run = SimpleNamespace(run_id="r1", status=RunStatus.error)
        with pytest.raises(RuntimeError, match="db down"):
            await apersist_run_transition(component, "agent", "s1", run)

    @pytest.mark.asyncio
    async def test_fallback_allowed_decision_table(self):
        assert fallback_allowed(RunPersistOutcome.MISSING) is True
        assert fallback_allowed(RunPersistOutcome.UNAVAILABLE) is True
        assert fallback_allowed(RunPersistOutcome.UNAVAILABLE) is True, (
            "no primitive: the fallback is the only write path, fenced callers included"
        )
        assert fallback_allowed(RunPersistOutcome.UPDATED) is False
        assert fallback_allowed(RunPersistOutcome.STALE_ATTEMPT) is False
        assert fallback_allowed(RunPersistOutcome.STALE_ATTEMPT) is False
        assert fallback_allowed(RunPersistOutcome.TERMINAL_REFUSED) is False
        assert fallback_allowed(RunPersistOutcome.TERMINAL_REFUSED) is False


class TestFenceFinality:
    """A fence rejection must never be overridden by the unfenced fallback
    (the zombie-clobber path from review)."""

    @pytest.mark.asyncio
    async def test_fenced_rejection_does_not_fall_back(self):
        class FencingDb:
            async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
                return RunPersistOutcome.STALE_ATTEMPT  # newer attempt owns the row

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
        class NoRowDb:
            async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None):
                return RunPersistOutcome.MISSING  # run not in session yet

        class FakeAgent:
            db = NoRowDb()

        result = await apersist_run_status(FakeAgent(), "agent", "s1", "r1", {"status": "error"})
        assert result is RunPersistOutcome.MISSING
        assert fallback_allowed(result) is True, "no row: the fallback creates it"

    @pytest.mark.asyncio
    async def test_no_adapter_support_falls_back(self):
        class BareDb:
            pass

        class FakeAgent:
            db = BareDb()

        result = await apersist_run_status(FakeAgent(), "agent", "s1", "r1", {"status": "error"})
        assert result is RunPersistOutcome.UNAVAILABLE
        assert fallback_allowed(result) is True, "no atomic primitive: fallback is the only option"


class TestGenerationStamping:
    @pytest.mark.asyncio
    async def test_stamped_generation_fences_zombie(self):
        """Attempt 2 stamps queue_attempt=2 at claim; attempt 1's late ERROR
        write (expected_attempt=1) must be rejected, not stamped vacuously.
        The fake returns legacy bools: the mapping must keep the fence."""
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
        assert r is RunPersistOutcome.UPDATED and stored["queue_attempt"] == 2

        # Attempt 1's zombie tries its terminal write
        r = await apersist_run_status(
            FakeAgent(), "agent", "s1", "r1", {"status": RunStatus.error.value}, expected_attempt=1
        )
        assert r is RunPersistOutcome.STALE_ATTEMPT, "zombie must be fenced by the stamped generation"
        assert fallback_allowed(r) is False
        assert stored["status"] == "running", "zombie write must not land"


class TestPreparedRunSerializes:
    def test_prepared_agent_run_round_trips(self):
        """The PENDING row aprepare builds must survive to_dict: a raw-string
        input made it raise inside the session save, so the row never landed
        (pollers 404'd and the attempt stamp found no run)."""
        from agno.run.agent import RunInput, RunOutput

        run = RunOutput(run_id="r1", session_id="s1", input=RunInput(input_content="hello"), status=RunStatus.pending)
        d = run.to_dict()
        assert d["input"]["input_content"] == "hello"
        assert RunOutput.from_dict(d).run_id == "r1"

    def test_prepared_team_run_round_trips(self):
        from agno.run.team import TeamRunInput, TeamRunOutput

        run = TeamRunOutput(
            run_id="r1", session_id="s1", input=TeamRunInput(input_content="hello"), status=RunStatus.pending
        )
        d = run.to_dict()
        assert d["input"]["input_content"] == "hello"
