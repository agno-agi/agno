"""Regression tests: a foreground STREAMING workflow that fails with a generic
exception must still persist the ERROR run.

Before the fix, _execute_stream / _aexecute_stream set status=error, yielded a
WorkflowErrorEvent, then ``raise e`` — but the terminal persist sat AFTER the
try/except (not in a finally), so the re-raise skipped it. The run was never
written to the runs store: get_run/aget_run returned None forever and /resume
could not surface the failure after a restart. This is asymmetric with the
non-streaming path (finally-wrapped), the cancelled branch (persists inline),
and agent/team streaming (persist ERROR via cleanup_and_store).

The custom-function (callable steps) branch had no generic handler at all, so a
generic exception propagated uncaught and skipped persistence the same way.

Note: a ``Step`` executor's own exception is caught + retried by the step
framework and does NOT escape to the generic handler, so these tests force an
exception that escapes the step loop (an orchestration error), or use the
callable branch which invokes the function directly.
"""

from __future__ import annotations

import pytest

from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def _ok_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content="ok")


def _boom_custom_function(execution_input) -> str:
    raise RuntimeError("callable exploded")


def _boom_orchestration(*args, **kwargs):
    # Escapes the step loop (unlike a Step executor error, which is caught/retried).
    raise RuntimeError("orchestration exploded")


def _drain(iterator) -> list:
    return [event for event in iterator]


async def _adrain(async_iterator) -> list:
    return [event async for event in async_iterator]


def _make_db(tmp_path, name: str = "wf.db") -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / name))


class TestStreamingWorkflowErrorPersist:
    def test_sync_multistep_stream_error_persists_error_run(self, tmp_path):
        wf = Workflow(name="wf", steps=[Step(name="s", executor=_ok_step)], db=_make_db(tmp_path))
        wf._create_step_input = _boom_orchestration  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="orchestration exploded"):
            _drain(wf.run("input", session_id="s1", run_id="r1", stream=True))

        run = wf.get_run("r1", session_id="s1")
        assert run is not None, "errored streaming run must be persisted, not lost"
        assert run.status == RunStatus.error

    async def test_async_multistep_stream_error_persists_error_run(self, tmp_path):
        wf = Workflow(name="wf", steps=[Step(name="s", executor=_ok_step)], db=_make_db(tmp_path))
        wf._create_step_input = _boom_orchestration  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="orchestration exploded"):
            await _adrain(wf.arun("input", session_id="s1", run_id="r1", stream=True))

        run = wf.get_run("r1", session_id="s1")
        assert run is not None, "errored async streaming run must be persisted, not lost"
        assert run.status == RunStatus.error

    def test_sync_callable_stream_error_persists_error_run(self, tmp_path):
        """The custom-function branch had no generic except at all."""
        wf = Workflow(name="wf", steps=_boom_custom_function, db=_make_db(tmp_path))

        with pytest.raises(RuntimeError, match="callable exploded"):
            _drain(wf.run("input", session_id="s1", run_id="r1", stream=True))

        run = wf.get_run("r1", session_id="s1")
        assert run is not None, "errored callable-workflow streaming run must be persisted"
        assert run.status == RunStatus.error

    def test_persist_failure_does_not_mask_original_exception(self, tmp_path):
        """If persistence itself fails on the error path, the ORIGINAL exception
        must still propagate (persist is guarded + logged)."""
        wf = Workflow(name="wf", steps=_boom_custom_function, db=_make_db(tmp_path))

        def _explode_persist(*args, **kwargs):
            raise RuntimeError("persist boom")

        wf._persist_session_and_run = _explode_persist  # type: ignore[method-assign]

        # The callable's RuntimeError, not the persistence one, must surface.
        with pytest.raises(RuntimeError, match="callable exploded"):
            _drain(wf.run("input", session_id="s1", run_id="r1", stream=True))

    def test_streaming_matches_nonstreaming_error_persistence(self, tmp_path):
        """Parity: non-streaming and streaming both persist an ERROR row."""
        wf_ns = Workflow(name="wf", steps=[Step(name="s", executor=_ok_step)], db=_make_db(tmp_path, "ns.db"))
        wf_ns._create_step_input = _boom_orchestration  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="orchestration exploded"):
            wf_ns.run("input", session_id="s1", run_id="r1")
        ns_run = wf_ns.get_run("r1", session_id="s1")
        assert ns_run is not None and ns_run.status == RunStatus.error

        wf_s = Workflow(name="wf", steps=[Step(name="s", executor=_ok_step)], db=_make_db(tmp_path, "s.db"))
        wf_s._create_step_input = _boom_orchestration  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="orchestration exploded"):
            _drain(wf_s.run("input", session_id="s1", run_id="r1", stream=True))
        s_run = wf_s.get_run("r1", session_id="s1")
        assert s_run is not None and s_run.status == RunStatus.error
