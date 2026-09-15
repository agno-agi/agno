"""The verification gate through the real Agent and Team run functions, on scripted offline models.

Covers the four run variants (run, run(stream=True), arun, arun(stream=True)) on both owners:
re-entry mechanics, statuses, the report message, events, the verification context in the system
message, reasoning and media across a re-entry, printers, the async verifier refusal on run(), and
stop_on_unchanged_state. Continuing a run through the gate is in test_gate_continue.py.
"""

import copy
import io
import logging
from typing import Any, List

import pytest
from rich.console import Console

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.metrics import MessageMetrics
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.base import RunStatus
from agno.team import Team
from agno.verifiers import VerificationConfig, check
from agno.verifiers.fingerprints import CallableFingerprint
from agno.verifiers.report import is_verification_report
from agno.verifiers.types import Verdict

from .conftest import (
    MODES,
    ScriptedModel,
    _image_response,
    _image_urls,
    _reports,
    _run_variant,
    _text,
    _tool_call,
    fail_once,
)

KINDS = pytest.mark.parametrize("kind", ["agent", "team"])


def _gated(kind: str, model: Any, **kwargs: Any):
    """An agent, or a one-member team (in tasks mode for "team_tasks"), on the given model."""
    kwargs.setdefault("telemetry", False)
    if kind == "agent":
        return Agent(model=model, **kwargs)
    if kind == "team_tasks":
        kwargs.setdefault("mode", "tasks")
    kwargs.setdefault("members", [Agent(name="member", id="member", model=ScriptedModel([_text("member ok")]))])
    return Team(model=model, **kwargs)


def _event(kind: str, name: str) -> str:
    return f"Team{name}" if kind == "team" else name


# ---------------------------------------------------------------------------
# Re-entry, statuses and the report, on both owners
# ---------------------------------------------------------------------------


@KINDS
@MODES
async def test_fail_then_pass_is_one_run(kind, mode):
    model = ScriptedModel([_text("claimed done"), _text("actually done")])
    owner = _gated(kind, model, verifiers=[fail_once()])
    out = await _run_variant(owner, mode)
    assert model.calls == 2
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert out.verification.stop_reason == "passed"
    assert len(out.verification.attempts) == 2
    assert out.verification.attempts[0].verdicts[0].passed is False
    assert out.verification.attempts[1].verdicts[0].passed is True
    reports = _reports(out)
    assert len(reports) == 1
    assert "[FAIL] report_exists: report.md is missing" in reports[0].content
    assert 'attempt="1/3"' in reports[0].content
    assert out.content == "actually done"
    mi = out.verification.attempts[1].message_index
    assert is_verification_report(out.messages[mi - 1])
    # The report is real transcript: persisted and replayed, not temporary.
    assert reports[0].add_to_agent_memory is True
    assert reports[0].temporary is False
    # Only the gate's own message counts as a report, not text that looks like one.
    assert not is_verification_report(Message(role="user", content="<verification> typed by a person"))
    assert not is_verification_report(Message(role="assistant", content='<verification attempt="1/2"'))


@pytest.mark.parametrize("kind, model_calls", [("agent", 3), ("team", 3), ("team_tasks", 6)])
@MODES
async def test_exhausted_ends_unverified(kind, model_calls, mode):
    """Tasks mode wraps the whole task loop, which answers in two leader turns per window
    (answer + reminder), so three attempts cost six calls."""
    model = ScriptedModel([_text("nope")])
    owner = _gated(kind, model, verifiers=[lambda run_output: "never good"])
    out = await _run_variant(owner, mode)
    assert model.calls == model_calls
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    assert out.verification.stop_reason == "exhausted"
    assert len(out.verification.attempts) == 3


@KINDS
@pytest.mark.parametrize("setting", ["default", "context_off", "no_verifiers"])
def test_verification_context_in_system_message(kind, setting):
    def report_exists(run_output):
        return True

    kwargs: Any = {"instructions": "Do the thing."}
    if setting != "no_verifiers":
        kwargs["verifiers"] = [report_exists]
    if setting == "context_off":
        kwargs["verification"] = VerificationConfig(add_verification_to_context=False)
    out = _gated(kind, ScriptedModel([_text("done")]), **kwargs).run("go")
    system = str(out.messages[0].content)
    assert out.messages[0].role == "system"
    if setting == "default":
        assert "Completion is checked by the host" in system
        assert "report_exists" in system
    else:
        assert "Completion is checked" not in system
    if setting == "no_verifiers":
        assert out.verification is None
        assert out.status == RunStatus.completed


@pytest.mark.parametrize(
    "make, error, match",
    [
        (lambda: VerificationConfig(max_attempts=0), ValueError, None),
        (lambda: VerificationConfig(stop_on_unchanged_state=True), ValueError, None),
        (lambda: Agent(verifiers="pytest -q"), TypeError, "verifiers must be a list"),
        (lambda: Agent(verifiers=lambda run_output: True), TypeError, "verifiers must be a list"),
        (lambda: Agent(verifiers=[lambda run_output: True], verification="yes"), TypeError, "verification must be"),
        (lambda: Agent(verifiers=[lambda run_output: True], verification=0), TypeError, "verification must be"),
        (lambda: Agent(verifiers=[lambda run_output: True], verification=[]), TypeError, "verification must be"),
    ],
    ids=["zero_attempts", "unchanged_state_without_fingerprint", "str", "callable", "yes", "zero", "list"],
)
def test_construction_errors(make, error, match):
    with pytest.raises(error, match=match):
        make()


@KINDS
async def test_run_refuses_an_async_verifier_before_the_model_call(kind):
    async def async_check(run_output):
        return True

    model = ScriptedModel([_text("done")])
    owner = _gated(kind, model, verifiers=[async_check])
    with pytest.raises(ValueError, match=r"async_check \(an async verifier\) with `run\(\)`"):
        owner.run("go")
    assert model.calls == 0
    assert (await owner.arun("go")).verification.status == "verified"


# ---------------------------------------------------------------------------
# Events and the terminal status on RunCompleted
# ---------------------------------------------------------------------------


@KINDS
@pytest.mark.parametrize("mode", ["run_stream", "arun_stream"])
async def test_stream_event_sequence(kind, mode):
    async def stream(owner):
        if mode == "run_stream":
            return list(owner.run("go", stream=True, stream_events=True, yield_run_output=True))
        return [e async for e in owner.arun("go", stream=True, stream_events=True, yield_run_output=True)]

    events = await stream(_gated(kind, ScriptedModel([_text("claimed"), _text("real")]), verifiers=[fail_once()]))
    names = [getattr(e, "event", "") for e in events]
    started, completed = _event(kind, "VerificationStarted"), _event(kind, "VerificationCompleted")
    assert names.count(started) == 2
    assert names.count(completed) == 2
    assert names.count(_event(kind, "RunContentCompleted")) == 1
    assert names.index(started) < names.index(completed)
    assert names.index(_event(kind, "RunContentCompleted")) > names.index(completed)
    completed_events = [e for e in events if getattr(e, "event", "") == completed]
    assert completed_events[0].passed is False and completed_events[0].attempt == 1
    assert completed_events[1].passed is True and completed_events[1].attempt == 2
    assert completed_events[1].stop_reason == "passed"
    assert completed_events[0].verdicts[0].name == "report_exists"

    failing = _gated(
        kind,
        ScriptedModel([_text("nope")]),
        verifiers=[lambda run_output: "never"],
        verification=VerificationConfig(max_attempts=2),
    )
    run_completed = [e for e in await stream(failing) if getattr(e, "event", "") == _event(kind, "RunCompleted")]
    assert len(run_completed) == 1
    assert run_completed[0].status == RunStatus.unverified.value
    assert run_completed[0].to_dict()["status"] == "UNVERIFIED"


# ---------------------------------------------------------------------------
# Verifier inputs and loop stops
# ---------------------------------------------------------------------------


@KINDS
def test_output_schema_verifier_sees_parsed_content(kind):
    from pydantic import BaseModel

    class Answer(BaseModel):
        value: int

    seen = {}

    def gate_check(run_output):
        seen["content"] = run_output.content
        return True

    owner = _gated(kind, ScriptedModel([_text('{"value": 41}')]), verifiers=[gate_check], output_schema=Answer)
    out = owner.run("go")
    assert isinstance(seen["content"], Answer)
    assert isinstance(out.content, Answer)


def test_timeout_stops_the_loop(monkeypatch):
    import agno.verifiers._gate as gate_mod

    clock = {"t": 0.0}

    def fake_monotonic():
        clock["t"] += 100.0
        return clock["t"]

    monkeypatch.setattr(gate_mod, "monotonic", fake_monotonic)
    model = ScriptedModel([_text("nope")])
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: False],
        verification=VerificationConfig(max_attempts=10, timeout=50.0),
    )
    out = agent.run("go")
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "timeout"
    assert len(out.verification.attempts) == 1


def test_retry_starts_with_a_fresh_record():
    """The transient error fires on the re-entry call, after attempt 1 already settled on the
    record. The model-level retry reruns the whole run on the same run_response: a resumed
    record would carry that settled attempt, whose message index points into the discarded
    transcript, into the retried run."""

    class FlakyModel(ScriptedModel):
        def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
            if self.calls == 1:
                self.calls += 1
                raise RuntimeError("transient")
            return self._next(kwargs)

    model = FlakyModel([_text("claimed"), _text("unused"), _text("done")])
    agent = Agent(model=model, verifiers=[fail_once()], retries=1, delay_between_retries=0)
    out = agent.run("go")
    assert model.calls == 3
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 1
    assert out.verification.attempts[0].verdicts[0].passed is True
    assert out.verification.budget_baseline == 0


def _silent() -> ModelResponse:
    """An assistant turn with no content and no tool calls."""
    response = ModelResponse(role="assistant")
    response.event = ModelResponseEvent.assistant_response.value
    response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
    return response


@KINDS
@MODES
async def test_reentry_with_no_text_drops_the_rejected_answer(kind, mode):
    """A streamed pass writes content only when a chunk arrives, so a re-entry that produces
    no text must not leave the rejected answer on the output. On a team the re-entered attempt
    answers by delegating: member deltas append onto whatever content the run carries, so the
    rejected answer must be cleared first or both the check and the final content read
    'WRONGmember ok'."""
    seen: List[Any] = []

    def gate_check(run_output):
        seen.append(copy.copy(run_output.content))
        return True if len(seen) > 1 else "wrong"

    if kind == "agent":
        script, answer = [_text("WRONG"), ModelResponse(role="assistant")], None
    else:
        redo = _tool_call("delegate_task_to_member", "tc-redo", {"member_id": "member", "task": "redo it"})
        # Member deltas land on the leader's content only on the stream paths.
        script, answer = [_text("WRONG"), redo, _silent()], "member ok" if mode.endswith("stream") else ""
    owner = _gated(kind, ScriptedModel(script), verifiers=[gate_check])
    out = await _run_variant(owner, mode)
    assert out.status == RunStatus.completed
    assert seen == ["WRONG", answer]
    assert out.content == answer


@KINDS
@MODES
async def test_reentry_restores_reasoning_to_its_pre_loop_value(kind, mode, monkeypatch):
    """Reasoning written before the attempt loop (the reasoning step) belongs to the run and
    survives a re-entry; reasoning a rejected attempt added does not reach the next check
    or the final output."""
    import agno.agent._response as agent_response
    import agno.team._response as team_response

    def reason(*args, run_response=None, **kwargs):
        run_response.reasoning_content = "thought it through"
        return iter(())

    async def areason(*args, run_response=None, **kwargs):
        run_response.reasoning_content = "thought it through"
        return
        yield

    module = agent_response if kind == "agent" else team_response
    monkeypatch.setattr(module, "reason", reason)
    monkeypatch.setattr(module, "areason", areason)
    rejected = _text("claimed")
    rejected.reasoning_content = "first thoughts"
    seen: List[Any] = []

    def gate_check(run_output):
        seen.append(run_output.reasoning_content)
        return True if len(seen) > 1 else "report.md is missing"

    owner = _gated(
        kind,
        ScriptedModel([rejected, _text("real")]),
        verifiers=[gate_check],
        reasoning_model=ScriptedModel([_text("unused")]),
    )
    out = await _run_variant(owner, mode)
    assert out.status == RunStatus.completed
    assert "first thoughts" in seen[0]
    assert seen[1] == "thought it through"
    assert out.reasoning_content == "thought it through"
    assert out.content == "real"


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_reentry_resets_citations_and_keeps_media(use_async):
    """The verifier sees the media of its own attempt: media accumulates across attempts like
    tools do, so a rejected attempt's drawing is never lost. Citations are per attempt;
    references accumulate from the knowledge tool across the run."""
    model = ScriptedModel(
        [
            _image_response("attempt 1", "http://x/img1.png"),
            _image_response("attempt 2", "http://x/img2.png"),
        ]
    )
    seen: List[int] = []

    def gate_check(run_output):
        seen.append(len(run_output.images or []))
        if len(seen) == 1:
            run_output.files = ["rejected.pdf"]
            run_output.citations = {"attempt": 1}
            run_output.references = ["ref-1"]
            return "not yet"
        return True

    agent = Agent(model=model, verifiers=[gate_check])
    out = await agent.arun("go") if use_async else agent.run("go")
    assert model.calls == 2
    assert out.verification.status == "verified"
    assert seen == [1, 2]
    assert _image_urls(out) == ["http://x/img1.png", "http://x/img2.png"]
    assert out.files == ["rejected.pdf"]
    assert out.citations is None
    assert out.references == ["ref-1"]


def test_tool_batch_checkpoint_keeps_earlier_attempts_tools():
    """A tool-batch checkpoint taken in a re-entered attempt merges into the run's tool
    list instead of replacing it; the first attempt's execution stays on the run."""
    calls = {"n": 0}

    def ping() -> str:
        """Ping."""
        calls["n"] += 1
        return "pong"

    model = ScriptedModel([_tool_call("ping", "c1"), _text("claimed"), _tool_call("ping", "c2"), _text("real")])
    agent = Agent(model=model, tools=[ping], db=InMemoryDb(), checkpoint="tool-batch", verifiers=[fail_once()])
    out = agent.run("go")
    assert out.status == RunStatus.completed
    assert calls["n"] == 2
    assert [t.tool_call_id for t in out.tools] == ["c1", "c2"]
    stored = agent.get_run_output(out.run_id, session_id=out.session_id)
    assert [t.tool_call_id for t in stored.tools] == ["c1", "c2"]


def test_message_index_ignores_replayed_history():
    agent = Agent(
        model=ScriptedModel([_text("first"), _text("second")]),
        verifiers=[lambda run_output: True],
        add_history_to_context=True,
        num_history_runs=3,
    )
    first = agent.run("one")
    second = agent.run("two", session_id=first.session_id)
    index = second.verification.attempts[0].message_index
    stored = [m for m in (second.messages or []) if not m.from_history]
    assert index < len(stored)
    assert stored[index].role == "assistant"
    assert stored[index].content == "second"


def test_check_names_are_the_declared_names_made_distinct():
    def named(run_output):
        return Verdict(passed=False, report="second failed", name="from-verdict")

    agent = Agent(
        model=ScriptedModel([_text("one"), _text("two")]),
        verifiers=[
            check(lambda run_output: "first failed", name="tests"),
            check(named, name="tests"),
        ],
        verification=VerificationConfig(max_attempts=2),
    )
    out = agent.run("go")
    assert [v.name for v in out.verification.attempts[0].verdicts] == ["tests", "tests #2"]
    report = str(_reports(out)[0].content)
    assert "[FAIL] tests: first failed" in report
    assert "[FAIL] tests #2: second failed" in report


# ---------------------------------------------------------------------------
# Serialization and printers
# ---------------------------------------------------------------------------


@KINDS
def test_to_dict_serializes_verifiers_and_verification(kind, caplog):
    def report_exists(run_output):
        return True

    class Judge:
        def verify(self, run_output):
            return True

    owner = _gated(
        kind,
        ScriptedModel([_text("x")]),
        name="gated",
        verifiers=[report_exists, Judge()],
        verification=VerificationConfig(max_attempts=2),
    )
    with caplog.at_level(logging.WARNING, logger="agno"):
        config = owner.to_dict()
    assert config["verifiers"][0] == {
        "name": "report_exists",
        "required": True,
        "max_retries": 0,
        "stop_on_failure": False,
    }
    # A protocol object serializes as its kind only; the registry cannot rebuild it.
    assert config["verifiers"][1]["type"] == "protocol"
    assert config["verification"] == {
        "max_attempts": 2,
        "timeout": None,
        "stop_on_unchanged_state": False,
        "add_verification_to_context": True,
    }
    assert "Could not serialize verifiers" not in caplog.text


@KINDS
def test_stream_printer_shows_only_the_accepted_attempt(kind):
    """The rejected attempt's deltas were already streamed; the re-entry replaces them on
    screen rather than appending, so the final panel holds one answer."""

    def printed(owner) -> str:
        buffer = io.StringIO()
        owner.print_response("go", console=Console(file=buffer, width=120), stream=True)
        return buffer.getvalue()

    text = printed(_gated(kind, ScriptedModel([_text("claimed"), _text("real")]), verifiers=[fail_once()]))
    assert "real" in text
    assert "claimed" not in text

    unverified = _gated(
        kind,
        ScriptedModel([_text("draft one"), _text("draft two")]),
        verifiers=[lambda run_output: "never"],
        verification=VerificationConfig(max_attempts=2),
    )
    text = printed(unverified)
    assert "draft two" in text
    assert "draft one" not in text
    assert "Response (" in text
    assert "Run Unverified" not in text


# ---------------------------------------------------------------------------
# stop_on_unchanged_state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check_passes, model_changes_state, max_attempts, calls, status, stop_reason, unchanged",
    [
        (False, False, 3, 1, RunStatus.unverified, "unchanged_state", [True]),
        (False, True, 2, 2, RunStatus.unverified, "exhausted", [False, False]),
        (True, False, 3, 1, RunStatus.completed, "passed", [True]),
    ],
    ids=["failed_unchanged_stops", "failed_changed_reenters", "passed_unchanged_verifies"],
)
@pytest.mark.parametrize("mode", ["run", "arun"])
async def test_unchanged_state_stop(
    check_passes, model_changes_state, max_attempts, calls, status, stop_reason, unchanged, mode
):
    """A failed attempt with an unchanged fingerprint ends the run after one model call
    without spending the rest of the budget; a changed attempt re-enters; a passing attempt
    verifies even when nothing changed."""
    state = {"v": "start"}
    mutations = [lambda: state.update(v="after-1"), lambda: state.update(v="after-2")] if model_changes_state else None
    model = ScriptedModel([_text("try 1"), _text("try 2")], mutations=mutations)
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: True if check_passes else "still failing"],
        verification=VerificationConfig(
            max_attempts=max_attempts,
            stop_on_unchanged_state=True,
            fingerprint=CallableFingerprint(lambda: state["v"]),
        ),
    )
    out = await _run_variant(agent, mode)
    assert model.calls == calls
    assert out.status == status
    assert out.verification.stop_reason == stop_reason
    assert [a.state_unchanged for a in out.verification.attempts] == unchanged


@pytest.mark.parametrize("mode", ["run", "arun"])
async def test_check_artefacts_do_not_read_as_model_progress(mode):
    """The comparison baseline settles after the checks run: state the checks themselves
    mutate is folded into the baseline, so a model attempt that changes nothing on top of
    its state is still unchanged. Were the baseline captured before the checks, attempt 2 would read
    the check's own mutation as progress, re-enter, and burn the rest of the budget."""
    state = {"v": "start"}

    def failing_check_that_mutates(run_output):
        state["v"] = state["v"] + "+check"
        return "still failing"

    model = ScriptedModel(
        [_text("try 1"), _text("try 2")],
        mutations=[lambda: state.update(v="model-1"), None],
    )
    agent = Agent(
        model=model,
        verifiers=[failing_check_that_mutates],
        verification=VerificationConfig(
            max_attempts=4,
            stop_on_unchanged_state=True,
            fingerprint=CallableFingerprint(lambda: state["v"]),
        ),
    )
    out = await _run_variant(agent, mode)
    assert model.calls == 2
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "unchanged_state"
    attempts = out.verification.attempts
    assert len(attempts) == 2
    # Attempt 1: the model's own mutation reads as progress.
    assert attempts[0].state_unchanged is False
    assert attempts[0].fingerprint == "model-1"
    # Attempt 2: compared against the post-check state, not the model's last capture.
    assert attempts[1].compared_against == "model-1+check"
    assert attempts[1].state_unchanged is True
