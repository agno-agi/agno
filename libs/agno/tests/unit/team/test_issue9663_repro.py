"""
Regression repro for: https://github.com/agno-agi/agno/issues/9663

[Bug] After /teams/{team_id}/runs/{run_id}/continue, member and team leader
re-execute when a member's HITL tool was rejected.

Setup that triggers it:
  - Team(members=[member with a requires_confirmation tool],
          determine_input_for_members=False, respond_directly=True)
  - member's HITL gated tool is REJECTED (confirmed=False + confirmation_note)
  - then team.continue_run is called

Expected behaviour:
  - member returns a cancellation/decline response; the team leader should
    forward that directly to the user and NOT re-invoke the team leader model
    (no re-delegation), and the member's gated tool must NOT execute.

This file only reproduces the current (buggy) behaviour; it is meant to fail
while the bug is present and pass once the fix lands.
"""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.base import RunStatus
from agno.team import Team, TeamRunOutput
from agno.tools import tool

# ---------------------------------------------------------------------------
# Shared state and model
# ---------------------------------------------------------------------------

_EXECUTED: list = []


@tool(requires_confirmation=True)
def send_email(to: str) -> str:
    _EXECUTED.append(to)
    return f"Email sent to {to}"


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tools',[...]) | ('tool',name,args,id) | ('content',text).

    Tracks the number of turns consumed via ``self._i`` so a test can assert
    whether the model was invoked at all.
    """

    def __init__(self, model_id: str, script: list):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tools":
            r = ModelResponse(role="assistant")
            r.tool_calls = [
                {"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for name, args, tcid in turn[1]
            ]
        elif turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        r.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return r

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


# ---------------------------------------------------------------------------
# Repro
# ---------------------------------------------------------------------------


def _build_team(db_file: str, resume: bool) -> Team:
    """Member tool requires confirmation; on resume the leader would re-delegate.

    If the leader model is invoked during continue_run (the bug), _i advances
    to 1 and it re-delegates; if the fix routes the decline straight to the
    user, the leader model is never called (_i stays 0).
    """
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel(
            "m-emailer",
            [("content", "The email sending was declined by the user.")]
            if resume
            else [("tool", "send_email", {"to": "a@example.com"}, "tc-send"), ("content", "Email sent.")],
        ),
        tools=[send_email],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader",
            [("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it again"}, "tc-deleg-resume")]
            if resume
            else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[emailer],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
        respond_directly=True,
        determine_input_for_members=False,
    )


def test_member_hitl_rejection_leader_must_not_redispatch(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe.db")
    session_id = "s-probe"

    # Phase 1: leader delegates; member pauses on the gated tool.
    team1 = _build_team(db_file, resume=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)

    assert run1.is_paused, "member HITL should pause the team run"
    assert _EXECUTED == []
    assert len(run1.requirements or []) == 1
    req = run1.requirements[0]
    assert req.member_agent_id == "emailer"
    assert not req.is_resolved()

    # Phase 2: user REJECTS the member's gated tool, then continues.
    req.reject("user declined email")
    assert req.is_resolved(), "a rejection resolves the requirement"
    assert req.tool_execution.confirmed is False
    assert req.tool_execution.confirmation_note == "user declined email"

    team2 = _build_team(db_file, resume=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=run1.requirements)

    # ---- bug assertion: the leader model must NOT be re-invoked ----
    # With the bug, continue_run routes member results back into the leader
    # model loop (_prepare_member_hitl_continuation + _continue_run), consuming
    # the first resume turn which would re-delegate. With the intended fix the
    # leader forwards the decline directly and never calls its model.
    assert team2.model._i == 0, (
        f"team leader model was invoked {team2.model._i} time(s) after a member "
        "HITL rejection; it should re-delegate / ask the user again. "
        "Regression for issue #9663."
    )

    # The gated member tool must never execute after a rejection.
    assert _EXECUTED == [], "the rejected member tool must not execute"

    # run2 should surface the member's decline to the user.
    assert run2.content is not None
    assert "declined" in str(run2.content).lower()


# ---------------------------------------------------------------------------
# Trimmed variant: even when the leader would produce a benign final answer,
# the leader model should still not be invoked on a member rejection.
# ---------------------------------------------------------------------------


def _build_team_benign_leader(db_file: str, resume: bool) -> Team:
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel(
            "m-emailer-2",
            [("content", "User declined the email.")]
            if resume
            else [("tool", "send_email", {"to": "b@example.com"}, "tc-send2"), ("content", "Email sent.")],
        ),
        tools=[send_email],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader-2",
            [("content", "Okay, I will not send it.")] if resume else [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg2"),
                ("content", "All done."),
            ],
        ),
        members=[emailer],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
        respond_directly=True,
        determine_input_for_members=False,
    )


def test_member_hitl_rejection_leader_forward_decline_without_model_call(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe2.db")
    session_id = "s-probe2"

    team1 = _build_team_benign_leader(db_file, resume=False)
    run1 = team1.run("Ask about b@example.com", session_id=session_id)
    assert run1.is_paused

    for req in run1.requirements or []:
        req.reject("no thanks")

    team2 = _build_team_benign_leader(db_file, resume=True)
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=run1.requirements)

    assert team2.model._i == 0, "team leader model should not be invoked on a member HITL rejection (issue #9663)"
    assert _EXECUTED == []
    assert run2.content is not None


# ---------------------------------------------------------------------------
# Positive control: when the member APPROVES the gated tool, the team leader
# must STILL wrap up the run (model invoked) and the tool must execute. This
# guards the rejection short-circuit from also short-circuiting approvals.
# ---------------------------------------------------------------------------


def test_member_hitl_approval_leader_still_wraps_up(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe_ok.db")
    session_id = "s-probe-ok"

    def _emailer(resume: bool) -> Agent:
        return Agent(
            name="Emailer",
            id="emailer",
            model=_ScriptedModel(
                "m-emailer-ok",
                [("content", "Email confirmed and sent.")]
                if resume
                else [("tool", "send_email", {"to": "c@example.com"}, "tc-ok"), ("content", "Email sent.")],
            ),
            tools=[send_email],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
        )

    def _team(resume: bool, emailer_agent: Agent) -> Team:
        return Team(
            name="Comms Team",
            id="comms-team",
            model=_ScriptedModel(
                "m-leader-ok",
                [("content", "All wrapped up.")]
                if resume
                else [("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-ok-deleg")],
            ),
            members=[emailer_agent],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
            respond_directly=True,
            determine_input_for_members=False,
        )

    team1 = _team(resume=False, emailer_agent=_emailer(resume=False))
    run1 = team1.run("Email c@example.com", session_id=session_id)
    assert run1.is_paused, "member HITL should pause the team run"
    assert _EXECUTED == []
    assert len(run1.requirements or []) == 1
    req = run1.requirements[0]
    assert not req.is_resolved()

    # Phase 2: user APPROVES the member's gated tool, then continues.
    req.confirm()
    assert req.is_resolved()
    assert req.tool_execution.confirmed is True

    team2 = _team(resume=True, emailer_agent=_emailer(resume=True))
    run2 = team2.continue_run(run_id=run1.run_id, session_id=session_id, requirements=run1.requirements)

    # The approved tool must execute, and the leader must still be invoked to
    # wrap up (i.e. the rejection short-circuit must NOT fire on approval).
    assert _EXECUTED == ["c@example.com"], "the approved member tool must execute"
    assert team2.model._i == 1, "team leader model should still be invoked after a member approval"
    assert run2.status == RunStatus.completed
    assert "wrapped up" in str(run2.content).lower()


# ---------------------------------------------------------------------------
# The short-circuit must hold in every variant of the move: sync streaming,
# async non-streaming, and async streaming. The leader model `_i` stays 0, the
# gated tool never executes, and the decline surfaces as the final content.
# ---------------------------------------------------------------------------


def _last_run_output(outputs) -> TeamRunOutput:
    """Return the last TeamRunOutput yielded by a streaming continue_run."""
    final = None
    for event in outputs:
        if isinstance(event, TeamRunOutput):
            final = event
    assert final is not None, "no final TeamRunOutput yielded"
    return final


def _reject_first_requirement(run1) -> None:
    assert len(run1.requirements or []) == 1
    for req in run1.requirements or []:
        req.reject("user declined")
    assert all(r.is_resolved() for r in (run1.requirements or []))


def test_member_hitl_rejection_leader_must_not_redispatch_streaming(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe_stream.db")
    session_id = "s-probe-stream"

    team1 = _build_team(db_file, resume=False)
    run1 = team1.run("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []
    _reject_first_requirement(run1)

    team2 = _build_team(db_file, resume=True)
    run2 = _last_run_output(
        team2.continue_run(
            run_id=run1.run_id, session_id=session_id, requirements=run1.requirements, stream=True, yield_run_output=True
        )
    )

    assert team2.model._i == 0, "streaming: leader model must not be re-invoked after a member rejection (#9663)"
    assert _EXECUTED == []
    assert run2.content is not None
    assert "declined" in str(run2.content).lower()


async def test_member_hitl_rejection_leader_must_not_redispatch_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe_async.db")
    session_id = "s-probe-async"

    team1 = _build_team(db_file, resume=False)
    run1 = await team1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []
    _reject_first_requirement(run1)

    team2 = _build_team(db_file, resume=True)
    run2 = await team2.acontinue_run(
        run_id=run1.run_id, session_id=session_id, requirements=run1.requirements
    )

    assert team2.model._i == 0, "async: leader model must not be re-invoked after a member rejection (#9663)"
    assert _EXECUTED == []
    assert run2.content is not None
    assert "declined" in str(run2.content).lower()


async def test_member_hitl_rejection_leader_must_not_redispatch_async_streaming(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe_async_stream.db")
    session_id = "s-probe-async-stream"

    team1 = _build_team(db_file, resume=False)
    run1 = await team1.arun("Email a@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []
    _reject_first_requirement(run1)

    team2 = _build_team(db_file, resume=True)
    run2 = _last_run_output(
        [
            event
            async for event in team2.acontinue_run(
                run_id=run1.run_id,
                session_id=session_id,
                requirements=run1.requirements,
                stream=True,
                yield_run_output=True,
            )
        ]
    )

    assert team2.model._i == 0, "async streaming: leader model must not be re-invoked after a member rejection (#9663)"
    assert _EXECUTED == []
    assert run2.content is not None
    assert "declined" in str(run2.content).lower()


async def test_member_hitl_approval_leader_still_wraps_up_async(tmp_path):
    _EXECUTED.clear()
    db_file = str(tmp_path / "probe_ok_async.db")
    session_id = "s-probe-ok-async"

    def _emailer(resume: bool) -> Agent:
        return Agent(
            name="Emailer",
            id="emailer",
            model=_ScriptedModel(
                "m-emailer-ok-async",
                [("content", "Email confirmed and sent.")]
                if resume
                else [("tool", "send_email", {"to": "d@example.com"}, "tc-ok-async"), ("content", "Email sent.")],
            ),
            tools=[send_email],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
        )

    def _team(resume: bool, emailer_agent: Agent) -> Team:
        return Team(
            name="Comms Team",
            id="comms-team",
            model=_ScriptedModel(
                "m-leader-ok-async",
                [("content", "All wrapped up.")]
                if resume
                else [("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-ok-async-deleg")],
            ),
            members=[emailer_agent],
            db=SqliteDb(db_file=db_file),
            telemetry=False,
            respond_directly=True,
            determine_input_for_members=False,
        )

    team1 = _team(resume=False, emailer_agent=_emailer(resume=False))
    run1 = await team1.arun("Email d@example.com", session_id=session_id)
    assert run1.is_paused
    assert _EXECUTED == []
    assert len(run1.requirements or []) == 1
    run1.requirements[0].confirm()

    team2 = _team(resume=True, emailer_agent=_emailer(resume=True))
    run2 = await team2.acontinue_run(run_id=run1.run_id, session_id=session_id, requirements=run1.requirements)

    # Approval: the tool executes and the leader is still invoked to wrap up.
    assert _EXECUTED == ["d@example.com"], "the approved member tool must execute"
    assert team2.model._i == 1, "async: team leader model should still be invoked after a member approval"
    assert run2.status == RunStatus.completed
    assert "wrapped up" in str(run2.content).lower()
