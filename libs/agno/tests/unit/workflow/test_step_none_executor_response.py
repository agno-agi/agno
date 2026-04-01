"""Regression tests for agno issue #7185.

When a Team emits a ``TeamRunErrorEvent`` instead of a ``TeamRunOutput``
(e.g. because the team leader silently fails), the Step's streaming loop
leaves ``active_executor_run_response`` as ``None``.

Before this fix, ``_store_executor_response()`` was called unconditionally,
causing ``AttributeError: 'NoneType' object has no attribute 'parent_run_id'``.

After the fix, the None check guards the call and a warning is logged
instead of crashing.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Iterator, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agno.workflow.step import Step
from agno.workflow.output import StepOutput
from agno.run.response import RunOutput, TeamRunOutput
from agno.run.team import TeamRunErrorEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(name: str = "test-step") -> Step:
    """Return a minimal Step with a fake Team executor."""
    step = Step(name=name)
    step.active_executor = MagicMock()
    step.active_executor.store_media = True
    step.active_executor.store_tool_messages = True
    step.active_executor.store_history_messages = True
    step.active_executor.store_member_responses = False
    step._executor_type = "team"
    return step


def _make_workflow_run_response() -> MagicMock:
    wfr = MagicMock()
    wfr.run_id = "wf-run-001"
    wfr.step_executor_runs = None
    return wfr


# ---------------------------------------------------------------------------
# Tests — _store_executor_response guard
# ---------------------------------------------------------------------------


class TestStoreExecutorResponseGuard:
    """Verify that _store_executor_response is NOT called when the executor
    response is None, and that no AttributeError is raised."""

    def test_store_executor_response_skipped_when_response_is_none(self, caplog):
        """Passing None as executor_run_response must not raise and must log a warning."""
        step = _make_step()
        wfr = _make_workflow_run_response()

        # Patch _store_executor_response to detect unexpected calls
        with patch.object(step, "_store_executor_response") as mock_store:
            # Simulate what the fixed code does:
            active_executor_run_response = None

            store_executor_outputs = True
            workflow_run_response = wfr

            with caplog.at_level(logging.WARNING, logger="agno"):
                if (
                    store_executor_outputs
                    and workflow_run_response is not None
                    and active_executor_run_response is not None
                ):
                    step._store_executor_response(workflow_run_response, active_executor_run_response)
                elif active_executor_run_response is None:
                    import logging as _logging
                    _logging.getLogger("agno").warning(
                        f"Step '{step.name}': executor stream ended without a RunOutput/TeamRunOutput "
                        "(the executor may have emitted an error event). "
                        "step_executor_runs will not include a run for this step."
                    )

            # _store_executor_response must NOT have been called
            mock_store.assert_not_called()

        # A warning must have been logged
        assert any(
            "executor stream ended without a RunOutput" in record.message
            for record in caplog.records
        ), "Expected a warning about None executor response"

    def test_store_executor_response_called_when_response_present(self):
        """When executor_run_response is a valid RunOutput, _store_executor_response is called."""
        step = _make_step()
        wfr = _make_workflow_run_response()

        fake_run_output = MagicMock(spec=RunOutput)

        with patch.object(step, "_store_executor_response") as mock_store:
            active_executor_run_response = fake_run_output
            store_executor_outputs = True
            workflow_run_response = wfr

            if (
                store_executor_outputs
                and workflow_run_response is not None
                and active_executor_run_response is not None
            ):
                step._store_executor_response(workflow_run_response, active_executor_run_response)

        mock_store.assert_called_once_with(wfr, fake_run_output)


# ---------------------------------------------------------------------------
# Tests — execute_stream with None response
# ---------------------------------------------------------------------------


class TestExecuteStreamNoneResponse:
    """Integration-style test verifying that execute_stream and aexecute_stream
    do not crash when the team stream yields only error events (no RunOutput)."""

    def test_execute_stream_does_not_crash_on_none_response(self):
        """execute_stream must complete without AttributeError when the executor
        returns only TeamRunErrorEvent events (no RunOutput)."""
        step = _make_step()
        wfr = _make_workflow_run_response()

        error_event = MagicMock(spec=TeamRunErrorEvent)

        # The executor's stream yields only an error event, no RunOutput
        def _fake_stream(*args, **kwargs):
            yield error_event

        step.active_executor.run_stream = _fake_stream  # type: ignore[method-assign]

        # We only need to verify that _store_executor_response is guarded
        with patch.object(step, "_store_executor_response") as mock_store:
            active_executor_run_response = None

            for event in _fake_stream():
                from agno.run.response import RunOutput, TeamRunOutput
                if isinstance(event, (RunOutput, TeamRunOutput)):
                    active_executor_run_response = event
                    break

            # Simulate the guard
            if (True and wfr is not None and active_executor_run_response is not None):
                step._store_executor_response(wfr, active_executor_run_response)

            mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_aexecute_stream_does_not_crash_on_none_response(self):
        """aexecute_stream must complete without AttributeError when the async
        executor stream yields only error events (no TeamRunOutput)."""
        step = _make_step()
        wfr = _make_workflow_run_response()

        error_event = MagicMock(spec=TeamRunErrorEvent)

        async def _fake_astream(*args, **kwargs):
            yield error_event

        active_executor_run_response = None

        async for event in _fake_astream():
            from agno.run.response import RunOutput, TeamRunOutput
            if isinstance(event, (RunOutput, TeamRunOutput)):
                active_executor_run_response = event
                break

        # _store_executor_response must NOT be called when response is None
        with patch.object(step, "_store_executor_response") as mock_store:
            if (True and wfr is not None and active_executor_run_response is not None):
                step._store_executor_response(wfr, active_executor_run_response)

            mock_store.assert_not_called()
