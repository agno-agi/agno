"""Unit tests for agno-agi/agno#8910: HITL resume can leave a PAUSED workflow
containing a CANCELLED sub-run (invariant: a PAUSED run must never be CANCELLED).

Root cause: when a stream/task is torn down (``asyncio.CancelledError`` /
``GeneratorExit`` — e.g. an SSE client disconnecting) at the exact moment a HITL
pause is being finalized, ``_handle_run_cancellation`` used to be invoked
unconditionally and would demote the run from PAUSED to CANCELLED, stripping the
pause markers (unresolved requirements, tool confirmation flags) needed to resume
it. That single mutation reproduces the reported bug: a run (and, when it is an
executor sub-run embedded in a workflow step, the enclosing *workflow* run) that is
reported PAUSED but can no longer be continued —
``RunNotContinuableError: Cannot continue run <id>: run is cancelled``.

``_is_disconnect_after_pause()`` is the fix: it distinguishes an explicit,
user-requested cancel (``RunCancelledException``, raised only after checking the
cancellation registry) from an implicit stream teardown (``asyncio.CancelledError``
/ ``GeneratorExit``), and treats the latter as a no-op once the run has already
finished pausing — mirroring the "reconcile" direction proposed in the issue, but
by preventing the corruption at the source instead of patching it up at resume time.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Set test API key to avoid env-var lookup errors when constructing OpenAI models.
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent._run import _handle_run_cancellation, _is_disconnect_after_pause, continue_run_dispatch
from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.exceptions import RunCancelledException, RunNotContinuableError
from agno.models.openai.responses import OpenAIResponses
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.team._run import _handle_team_run_cancellation
from agno.team._run import _is_disconnect_after_pause as _team_is_disconnect_after_pause


def _paused_run_with_pending_confirmation(run_id: str = "run-1", session_id: str = "s1") -> RunOutput:
    """A HITL-paused run: one tool awaiting confirmation, one unresolved requirement.

    Mirrors what a real agent run looks like right after ``ahandle_agent_run_paused*``
    sets ``status = RunStatus.paused`` — before the disconnect races it.
    """
    tool = ToolExecution(
        tool_call_id="call_1",
        tool_name="dangerous_action",
        tool_args={},
        requires_confirmation=True,
    )
    return RunOutput(
        run_id=run_id,
        session_id=session_id,
        status=RunStatus.paused,
        tools=[tool],
        requirements=[RunRequirement(tool_execution=tool)],
    )


def _paused_team_run_with_pending_confirmation(run_id: str = "team-run-1", session_id: str = "s1") -> TeamRunOutput:
    tool = ToolExecution(
        tool_call_id="call_1",
        tool_name="dangerous_action",
        tool_args={},
        requires_confirmation=True,
    )
    return TeamRunOutput(
        run_id=run_id,
        session_id=session_id,
        status=RunStatus.paused,
        tools=[tool],
        requirements=[RunRequirement(tool_execution=tool)],
    )


class TestIsDisconnectAfterPause:
    """Direct coverage of the classifier that gates the fix (agent + team variants)."""

    def test_generator_exit_after_pause_is_treated_as_disconnect(self):
        run = _paused_run_with_pending_confirmation()
        assert _is_disconnect_after_pause(GeneratorExit(), run) is True

    def test_cancelled_error_after_pause_is_treated_as_disconnect(self):
        run = _paused_run_with_pending_confirmation()
        assert _is_disconnect_after_pause(asyncio.CancelledError(), run) is True

    def test_keyboard_interrupt_is_never_treated_as_disconnect(self):
        # Ctrl-C is a deliberate, synchronous user action, not a torn-down stream —
        # it must keep going through the existing "cancel wins over paused" path.
        run = _paused_run_with_pending_confirmation()
        assert _is_disconnect_after_pause(KeyboardInterrupt(), run) is False

    def test_run_cancelled_exception_is_never_treated_as_disconnect(self):
        # An explicit /cancel call is a confirmed cancel intent, never a disconnect.
        run = _paused_run_with_pending_confirmation()
        assert _is_disconnect_after_pause(RunCancelledException("cancelled by user"), run) is False

    def test_generator_exit_before_pause_is_not_flagged(self):
        # The run hasn't actually finished pausing yet — a teardown here is a
        # genuine cancellation, not a race with pause finalization.
        run = _paused_run_with_pending_confirmation()
        run.status = RunStatus.running
        assert _is_disconnect_after_pause(GeneratorExit(), run) is False

    def test_generator_exit_on_already_cancelled_run_is_not_flagged(self):
        run = _paused_run_with_pending_confirmation()
        run.status = RunStatus.cancelled
        assert _is_disconnect_after_pause(GeneratorExit(), run) is False

    def test_team_variant_matches_agent_variant(self):
        run = _paused_team_run_with_pending_confirmation()
        assert _team_is_disconnect_after_pause(GeneratorExit(), run) is True
        assert _team_is_disconnect_after_pause(KeyboardInterrupt(), run) is False


class TestHandleRunCancellationIsStillDestructive:
    """Documents *why* the guard is needed: `_handle_run_cancellation` itself is
    unchanged and still unconditional (explicit cancels must keep winning over a
    paused run). If it fires on an already-paused run, it destroys exactly the
    state needed to resume — which is what used to happen on every disconnect."""

    def test_calling_handle_run_cancellation_on_a_paused_run_corrupts_it(self):
        run = _paused_run_with_pending_confirmation()
        corrupted = _handle_run_cancellation(run, KeyboardInterrupt(), None)

        assert corrupted.status == RunStatus.cancelled
        assert corrupted.tools[0].requires_confirmation is False  # pause marker destroyed
        assert corrupted.requirements == []  # unresolved requirement dropped -> unresumable

    def test_team_variant_is_equally_destructive(self):
        run = _paused_team_run_with_pending_confirmation()
        corrupted = _handle_team_run_cancellation(run, KeyboardInterrupt(), None, session=None)

        assert corrupted.status == RunStatus.cancelled
        assert corrupted.tools[0].requires_confirmation is False
        assert corrupted.requirements == []


def _simulate_disconnect_call_site(run_response: RunOutput, cancel_exc: BaseException) -> RunOutput:
    """Mirrors the guard now present at every
    `except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit)` call site in
    agent/_run.py and team/_run.py."""
    if _is_disconnect_after_pause(cancel_exc, run_response):
        return run_response
    return _handle_run_cancellation(run_response, KeyboardInterrupt(), None)


class TestDisconnectDuringPauseFinalizationPreservesInvariant:
    """Reproduces the issue's race (agno-agi/agno#8910) and asserts the PAUSED
    invariant holds after the disconnect — i.e. the run stays genuinely resumable,
    not just PAUSED-labeled with its pause data already gone."""

    def test_paused_run_survives_disconnect_and_stays_resumable(self):
        run = _paused_run_with_pending_confirmation()

        # Client disconnects (GeneratorExit) exactly as the HITL pause finishes persisting.
        result = _simulate_disconnect_call_site(run, GeneratorExit())

        assert result.status == RunStatus.paused
        assert result.tools[0].requires_confirmation is True
        assert len(result.requirements) == 1

    def test_explicit_cancel_of_a_paused_run_still_wins(self):
        # Regression guard: a genuine user-initiated cancel (RunCancelledException,
        # not a disconnect) must still demote a paused run, exactly as before the fix.
        run = _paused_run_with_pending_confirmation()
        result = _simulate_disconnect_call_site(run, RunCancelledException("cancelled by user"))
        assert result.status == RunStatus.cancelled

    def test_revert_proof_without_guard_disconnect_corrupts_paused_run(self):
        """If the guard is bypassed (the pre-fix behavior: every disconnect call site
        called `_handle_run_cancellation` unconditionally), the same disconnect
        reproduces exactly the invariant-violating state the issue reports."""
        run = _paused_run_with_pending_confirmation()
        corrupted = _handle_run_cancellation(run, KeyboardInterrupt(), None)  # pre-fix call site behavior
        assert corrupted.status == RunStatus.cancelled
        assert corrupted.requirements == []


class TestResumeAfterDisconnectDoesNotRaiseRunNotContinuable:
    """End-to-end: the exact crash reported in the issue is
    `RunNotContinuableError: Cannot continue run <id>: run is cancelled`, raised by
    `continue_run_dispatch` the moment it sees `status == RunStatus.cancelled` —
    before any model call. A run that survived the disconnect with `status == paused`
    must not trip that guard; a run that was actually cancelled still must."""

    def _make_agent(self) -> Agent:
        agent = Agent(
            name="test-agent",
            id="test-agent",
            model=OpenAIResponses(id="gpt-5.4"),
            db=InMemoryDb(),
            telemetry=False,
        )
        agent.initialize_agent()
        return agent

    def test_cancelled_run_cannot_be_continued(self):
        agent = self._make_agent()
        run = _paused_run_with_pending_confirmation(run_id="run-cancelled", session_id="s-cancelled")
        run.status = RunStatus.cancelled  # simulates the pre-fix disconnect corruption

        with pytest.raises(RunNotContinuableError):
            agent.continue_run(run_response=run, session_id="s-cancelled", stream=False)

    def test_paused_run_preserved_after_disconnect_does_not_raise_run_not_continuable(self):
        agent = self._make_agent()
        run = _paused_run_with_pending_confirmation(run_id="run-preserved", session_id="s-preserved")

        # Simulate the disconnect race using the fixed guard — the run stays PAUSED.
        preserved = _simulate_disconnect_call_site(run, GeneratorExit())
        assert preserved.status == RunStatus.paused

        # continue_run_dispatch's cancelled-status guard must not fire for this run.
        # (We don't drive it all the way through a real model call here — that's
        # covered by integration tests — only that the specific invariant guard the
        # issue reports tripping does not trip.)
        try:
            continue_run_dispatch(
                agent=agent,
                run_response=preserved,
                requirements=preserved.requirements,
                session_id="s-preserved",
                stream=False,
            )
        except RunNotContinuableError:
            raise AssertionError(
                "A run preserved as PAUSED after a stream disconnect must remain "
                "continuable — got RunNotContinuableError, meaning the invariant "
                "(agno-agi/agno#8910) was violated."
            )
        except Exception:
            # Any failure past the cancelled-status guard (e.g. a real model call
            # failing without network access) is out of scope for this test.
            pass
