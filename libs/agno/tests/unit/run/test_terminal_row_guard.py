"""Terminal-row protection and atomic prepare (tip review batch).

Covers: a sweep/drain must not overwrite a COMPLETED/CANCELLED run row; the
atomic append-if-absent path in aprepare wins over the legacy read-save race.
"""

from typing import Any, Dict, Optional

import pytest

from agno.run.base import RunStatus


class TestTerminalRowGuardFallback:
    @pytest.mark.asyncio
    async def test_sweep_fallback_does_not_overwrite_completed(self):
        """_persist_run_error's whole-session fallback must skip a run row
        that already reached completed (zombie finished, complete_job never
        landed, sweeper fires)."""
        from agno.job_queue.config import QueueConfig
        from agno.os.job_queue import QueueWorker
        from agno.run.agent import RunOutput

        completed_run = RunOutput(run_id="r1", session_id="s1", status=RunStatus.completed)
        saves: list = []

        class FakeSession:
            def get_run(self, run_id):
                return completed_run

            def upsert_run(self, run=None, run_response=None):
                saves.append(run or run_response)

        class FakeAgent:
            id = "a1"
            db = None  # no atomic primitive -> fallback path

        import agno.agent._session as sess_mod
        import agno.agent._storage as store_mod

        orig_read, orig_save = store_mod.aread_or_create_session, sess_mod.asave_session

        async def fake_read(component, session_id=None, user_id=None):
            return FakeSession()

        async def fake_save(component, session=None, **kw):
            saves.append("saved")

        store_mod.aread_or_create_session = fake_read
        sess_mod.asave_session = fake_save
        try:
            worker = QueueWorker(
                store=None,
                resolve_component=lambda t, i: FakeAgent(),
                config=QueueConfig(durable=True),
            )
            await worker._persist_run_error(
                {"id": "r1", "component_type": "agent", "component_id": "a1", "session_id": "s1", "attempt": 1},
                "worker lost",
            )
        finally:
            store_mod.aread_or_create_session = orig_read
            sess_mod.asave_session = orig_save

        assert completed_run.status == RunStatus.completed, "sweep must not rewrite a completed run"


class TestAtomicPrepare:
    @pytest.mark.asyncio
    async def test_prepare_uses_atomic_append_when_available(self):
        from agno.os.job_queue import aprepare_queued_run

        calls: Dict[str, Any] = {}

        class Db:
            async def append_run_to_session_if_absent(
                self, session_id: str, run_dict: Dict[str, Any], user_id: Optional[str] = None
            ):
                calls["run_dict"] = run_dict
                return True

        class FakeAgent:
            id = "a1"
            name = "A"
            db = Db()

        await aprepare_queued_run(FakeAgent(), "agent", run_id="r9", session_id="s9", user_id="u1", input="hi")
        assert calls["run_dict"]["run_id"] == "r9"
        assert str(calls["run_dict"]["status"]).lower() == "pending"

    @pytest.mark.asyncio
    async def test_prepare_defers_to_existing_worker_row(self):
        """False from the primitive means a worker already wrote the run -
        prepare must do nothing further (no legacy fallback save)."""
        from agno.os.job_queue import aprepare_queued_run

        class Db:
            async def append_run_to_session_if_absent(self, session_id, run_dict, user_id=None):
                return False

        class FakeAgent:
            id = "a1"
            name = "A"
            db = Db()

        # Would raise if the legacy path ran (no storage helpers patched)
        await aprepare_queued_run(FakeAgent(), "agent", run_id="r9", session_id="s9", user_id=None, input="hi")
