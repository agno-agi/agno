"""The verification gate through the agent and team CONTINUE functions, on scripted offline models.

- continuing an UNVERIFIED run resumes in place, keeps the attempt history, restarts the budget
  window and re-captures the fingerprint baseline; a failed continuation attempt re-enters inside
  the continue loop, and a continuation that never passes stays unverified;
- continuing a COMPLETED run forks, and the fork's record starts fresh;
- a HITL pause runs no checks, and the confirmed resume runs the gate in the same budget window
  against the baseline stored before the pause;
- a background continue publishes UNVERIFIED on the event stream.
"""

import asyncio
from typing import Any, Dict, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os.event_streams.in_memory import InMemoryEventStream
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools import tool
from agno.verifiers import VerificationConfig
from agno.verifiers.fingerprints import CallableFingerprint

from .conftest import MODES, ScriptedModel, _confirmed, _image_response, _image_urls, _run_variant, _text, _tool_call

KINDS = pytest.mark.parametrize("kind", ["agent", "team"])


def _gated(kind: str, model: Any, **kwargs: Any):
    """An agent, or a one-member team, on the given model."""
    kwargs.setdefault("telemetry", False)
    if kind == "agent":
        return Agent(model=model, **kwargs)
    kwargs.setdefault("members", [Agent(name="member", id="member", model=ScriptedModel([_text("member ok")]))])
    return Team(model=model, **kwargs)


@KINDS
@pytest.mark.parametrize("mode", ["continue", "acontinue", "continue_stream", "acontinue_stream"])
@pytest.mark.parametrize("recovers", [True, False], ids=["one_failure_then_pass", "still_failing"])
async def test_continue_of_unverified_run(kind, mode, recovers):
    """Continuing an unverified run stays in place: the history is kept, the budget window
    restarts at the continuation boundary, the baseline is captured again, a failed
    continuation attempt re-enters the continue loop with the attempt's media, and the stream
    legs emit that window's events. A continuation that never passes stays UNVERIFIED."""
    state = {"v": "before the run"}
    seen_images: List[int] = []

    def check(run_output):
        seen_images.append(len(run_output.images or []))
        # The first run spends two attempts; a recovering continuation passes on its second.
        return True if recovers and len(seen_images) == 4 else "not good enough"

    model = ScriptedModel([_text("try 1"), _text("try 2")])
    owner = _gated(
        kind,
        model,
        verifiers=[check],
        verification=VerificationConfig(max_attempts=2, fingerprint=CallableFingerprint(lambda: state["v"])),
    )
    use_async = mode.startswith("a")
    out = await owner.arun("go") if use_async else owner.run("go")
    assert out.status == RunStatus.unverified
    assert len(out.verification.attempts) == 2

    state["v"] = "changed between the runs"
    model.script = [
        _image_response("with chart", "http://x/chart-1.png"),
        _image_response("again", "http://x/chart-2.png"),
    ]
    kwargs: Dict[str, Any] = dict(run_response=out, input="try harder", session_id=out.session_id)
    events: List[Any] = []
    if mode == "continue":
        continued = owner.continue_run(**kwargs)
    elif mode == "acontinue":
        continued = await owner.acontinue_run(**kwargs)
    else:
        kwargs.update(stream=True, stream_events=True, yield_run_output=True)
        if mode == "continue_stream":
            events = list(owner.continue_run(**kwargs))
        else:
            events = [e async for e in owner.acontinue_run(**kwargs)]
        output_type = TeamRunOutput if kind == "team" else RunOutput
        continued = [e for e in events if isinstance(e, output_type)][-1]

    assert continued.run_id == out.run_id
    assert continued.forked_from_run_id is None
    assert model.calls == 4
    record = continued.verification
    assert len(record.attempts) == 4
    assert record.budget_baseline == 2
    assert [v.passed for a in record.attempts for v in a.verdicts] == [False, False, False, recovers]
    assert record.attempts[2].compared_against == "changed between the runs"
    if recovers:
        assert continued.status == RunStatus.completed
        assert (record.status, record.stop_reason) == ("verified", "passed")
    else:
        assert continued.status == RunStatus.unverified
        assert (record.status, record.stop_reason) == ("unverified", "exhausted")
    if kind == "agent":
        assert seen_images == [0, 0, 1, 2]
        assert _image_urls(continued)[-1] == "http://x/chart-2.png"
    if events:
        prefix = "Team" if kind == "team" else ""
        names = [getattr(e, "event", "") for e in events]
        assert names.count(f"{prefix}VerificationStarted") == 2
        completed = [e for e in events if getattr(e, "event", "") == f"{prefix}VerificationCompleted"]
        assert [e.attempt for e in completed] == [1, 2]


@KINDS
def test_continue_of_completed_run_forks_with_a_fresh_record(kind):
    """Continuing a COMPLETED (verified) run forks a sibling whose record starts fresh and
    re-verifies within its own budget; the parent's record is untouched."""
    owner = _gated(kind, ScriptedModel([_text("first"), _text("second")]), verifiers=[lambda run_output: True])
    out = owner.run("go")
    assert out.status == RunStatus.completed
    parent_record = out.verification

    continued = owner.continue_run(run_response=out, input="one more thing", session_id=out.session_id)

    assert continued.run_id != out.run_id
    assert continued.forked_from_run_id == out.run_id
    assert continued.status == RunStatus.completed
    record = continued.verification
    assert record is not parent_record
    assert (record.status, record.stop_reason, record.budget_baseline) == ("verified", "passed", 0)
    assert len(record.attempts) == 1
    assert out.verification is parent_record
    assert len(parent_record.attempts) == 1


@MODES
@pytest.mark.parametrize("reentered", [False, True], ids=["first_attempt", "reentered_attempt"])
async def test_hitl_pause_resumes_into_the_gate(tmp_path, mode, reentered):
    """A paused attempt runs no checks: the record stays pending, and a pause inside a
    re-entered attempt ends the run PAUSED without calling the model again. The confirmed
    resume finishes the turn inside the same budget window, and its attempt is compared
    against the baseline stored before the pause: the confirmed tool's change belongs to
    that attempt."""
    state = {"v": "before the pause"}

    @tool(requires_confirmation=True)
    def write_report() -> str:
        """Write the report."""
        state["v"] = "report written"
        return "written"

    calls = {"n": 0}

    def counting(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 or not reentered else "report.md is missing"

    script = [_tool_call("write_report", "tc-1"), _text("finished the job")]
    if reentered:
        script.insert(0, _text("claimed done"))
    model = ScriptedModel(script)
    agent = Agent(
        model=model,
        tools=[write_report],
        verifiers=[counting],
        verification=VerificationConfig(fingerprint=CallableFingerprint(lambda: state["v"])),
        db=SqliteDb(db_file=str(tmp_path / "hitl.db")),
        telemetry=False,
    )

    paused = await _run_variant(agent, mode, session_id="s-hitl")
    assert paused.is_paused
    assert paused.status == RunStatus.paused
    assert model.calls == len(script) - 1
    assert calls["n"] == int(reentered)
    assert paused.verification.status == "pending"
    assert len(paused.verification.attempts) == int(reentered)

    continued = agent.continue_run(
        run_id=paused.run_id, session_id="s-hitl", requirements=_confirmed(paused.requirements)
    )

    assert continued.run_id == paused.run_id
    assert continued.status == RunStatus.completed
    assert continued.content == "finished the job"
    assert calls["n"] == 1 + int(reentered)
    record = continued.verification
    assert (record.status, record.stop_reason, record.budget_baseline) == ("verified", "passed", 0)
    attempt = record.attempts[-1]
    assert len(record.attempts) == 1 + int(reentered)
    assert attempt.compared_against == "before the pause"
    assert attempt.fingerprint == "report written"
    assert attempt.state_unchanged is False


@pytest.mark.parametrize("fork", [False, True], ids=["in_place", "fork"])
async def test_background_continue_of_unverified_team_run_publishes_unverified(tmp_path, monkeypatch, fork):
    """A run-id-only background continue whose leg re-exhausts the budget parks the run
    UNVERIFIED, and a fork keeps the source key on the source's stored status. Neither
    terminal event-stream write may coerce that to COMPLETED."""
    import agno.os.event_streams as es_mod

    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(es_mod, "_event_stream", stream)
    team = _gated(
        "team",
        ScriptedModel([_text("nope")]),
        verifiers=[lambda run_output: "never"],
        verification=VerificationConfig(max_attempts=1),
        db=SqliteDb(db_file=str(tmp_path / "background.db")),
    )
    out = await team.arun("go", session_id="s-bg")
    assert out.status == RunStatus.unverified

    kwargs: Dict[str, Any] = dict(run_id=out.run_id, session_id="s-bg", stream=True, background=True)
    if fork:
        kwargs["fork"] = True
    else:
        kwargs["input"] = "again"
    chunks = [chunk async for chunk in team.acontinue_run(**kwargs)]
    assert chunks

    async def terminal_status():
        while (status := await stream.get_run_status(out.run_id)) in (None, RunStatus.pending, RunStatus.running):
            await asyncio.sleep(0.01)
        return status

    assert await asyncio.wait_for(terminal_status(), timeout=5.0) == RunStatus.unverified
