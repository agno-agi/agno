"""The verification gate through the real Agent run functions, on a scripted offline model.

Covers the four run variants (run, run(stream=True), arun, arun(stream=True)): re-entry
mechanics, statuses, the report message, events, the system-message notice, persistence
round-trips, and the async/sync verifier bridge.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.verifiers import VerificationConfig


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order."""

    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self

    def _next(self) -> ModelResponse:
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def fail_once():
    calls = {"n": 0}

    def report_exists(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 else "report.md is missing"

    return report_exists


def _run_variant(agent: Agent, mode: str, prompt: str = "go") -> RunOutput:
    """Drive one of the four run variants to its final RunOutput."""
    if mode == "run":
        return agent.run(prompt)
    if mode == "arun":
        return asyncio.run(agent.arun(prompt))
    if mode == "run_stream":
        events = list(agent.run(prompt, stream=True, stream_events=True, yield_run_output=True))
        return [e for e in events if isinstance(e, RunOutput)][-1]
    if mode == "arun_stream":

        async def collect():
            out = []
            async for e in agent.arun(prompt, stream=True, stream_events=True, yield_run_output=True):
                out.append(e)
            return out

        events = asyncio.run(collect())
        return [e for e in events if isinstance(e, RunOutput)][-1]
    raise AssertionError(mode)


MODES = ["run", "arun", "run_stream", "arun_stream"]


@pytest.mark.parametrize("mode", MODES)
def test_fail_then_pass_is_one_run(mode):
    model = ScriptedModel([_text("claimed done"), _text("actually done")])
    agent = Agent(model=model, verifiers=[fail_once()])
    out = _run_variant(agent, mode)
    assert model.calls == 2
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert out.verification.stop_reason == "passed"
    assert len(out.verification.attempts) == 2
    assert out.verification.attempts[0].verdicts[0].passed is False
    assert out.verification.attempts[1].verdicts[0].passed is True
    reports = [m for m in (out.messages or []) if m.role == "user" and "<verification" in str(m.content)]
    assert len(reports) == 1
    assert "[FAIL] report_exists: report.md is missing" in reports[0].content
    assert 'attempt="1/3"' in reports[0].content
    assert out.content == "actually done"
    mi = out.verification.attempts[1].message_index
    assert out.messages[mi - 1].role == "user" and "<verification" in str(out.messages[mi - 1].content)
    # The report is real transcript: persisted and replayed, not temporary.
    assert reports[0].add_to_agent_memory is True
    assert reports[0].temporary is False


@pytest.mark.parametrize("mode", MODES)
def test_exhausted_ends_unverified(mode):
    model = ScriptedModel([_text("nope")])
    agent = Agent(model=model, verifiers=[lambda run_output: "never good"])
    out = _run_variant(agent, mode)
    assert model.calls == 3
    assert out.status == RunStatus.unverified
    assert out.verification.status == "unverified"
    assert out.verification.stop_reason == "exhausted"
    assert len(out.verification.attempts) == 3


@pytest.mark.parametrize("mode", MODES)
def test_pass_first_attempt(mode):
    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[lambda run_output: True])
    out = _run_variant(agent, mode)
    assert model.calls == 1
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 1


def test_notice_in_system_message():
    model = ScriptedModel([_text("done")])
    agent = Agent(model=model, verifiers=[lambda run_output: True], instructions="Do the thing.")
    out = agent.run("go")
    system = out.messages[0]
    assert system.role == "system"
    assert "Completion is checked by the host" in str(system.content)
    assert "report_exists" not in str(system.content)


def test_notice_carries_verifier_names():
    model = ScriptedModel([_text("done")])

    def report_exists(run_output):
        return True

    agent = Agent(model=model, verifiers=[report_exists])
    out = agent.run("go")
    assert "report_exists" in str(out.messages[0].content)


def test_add_notice_false_suppresses_the_notice():
    model = ScriptedModel([_text("done")])
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: True],
        verification=VerificationConfig(add_notice=False),
        instructions="Do the thing.",
    )
    out = agent.run("go")
    assert "Completion is checked by the host" not in str(out.messages[0].content)


def test_no_verifiers_no_notice_no_record():
    model = ScriptedModel([_text("plain")])
    agent = Agent(model=model, instructions="x")
    out = agent.run("hi")
    assert out.verification is None
    assert out.status == RunStatus.completed
    assert "Completion is checked" not in str(out.messages[0].content)


def test_max_attempts_config_honoured():
    model = ScriptedModel([_text("nope")])
    agent = Agent(
        model=model,
        verifiers=[lambda run_output: False],
        verification=VerificationConfig(max_attempts=1),
    )
    out = agent.run("go")
    assert model.calls == 1
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "exhausted"


def test_construction_errors():
    with pytest.raises(ValueError):
        VerificationConfig(max_attempts=0)
    with pytest.raises(ValueError):
        VerificationConfig(stop_on_noop=True)
    with pytest.raises(ValueError):
        Agent(model=ScriptedModel([_text("x")]), verifiers=[object()])
    with pytest.raises(TypeError):
        Agent(model=ScriptedModel([_text("x")]), verifiers=[lambda unknown_name: True])


def test_persistence_round_trip():
    model = ScriptedModel([_text("nope")])
    agent = Agent(model=model, verifiers=[lambda run_output: "still wrong"])
    out = agent.run("go")
    data = json.loads(json.dumps(out.to_dict(), default=str))
    back = RunOutput.from_dict(data)
    assert back.verification is not None
    assert back.verification.status == "unverified"
    assert back.verification.attempts[0].verdicts[0].report == "still wrong"
    assert back.status == RunStatus.unverified


def test_async_verifier_on_sync_run_and_vice_versa():
    async def async_check(run_output):
        return True

    agent = Agent(model=ScriptedModel([_text("done")]), verifiers=[async_check])
    assert agent.run("go").verification.status == "verified"

    def sync_check(run_output):
        return True

    agent2 = Agent(model=ScriptedModel([_text("done")]), verifiers=[sync_check])
    assert asyncio.run(agent2.arun("go")).verification.status == "verified"


def test_stream_event_sequence():
    model = ScriptedModel([_text("claimed"), _text("real")])
    agent = Agent(model=model, verifiers=[fail_once()])
    events = list(agent.run("go", stream=True, stream_events=True, yield_run_output=True))
    names = [getattr(e, "event", "") for e in events]
    assert names.count("VerificationStarted") == 2
    assert names.count("VerificationCompleted") == 2
    assert names.count("RunContentCompleted") == 1
    first_started = names.index("VerificationStarted")
    first_completed = names.index("VerificationCompleted")
    assert first_started < first_completed
    assert names.index("RunContentCompleted") > names.index("VerificationCompleted")
    completed_events = [e for e in events if getattr(e, "event", "") == "VerificationCompleted"]
    assert completed_events[0].passed is False and completed_events[0].attempt == 1
    assert completed_events[1].passed is True and completed_events[1].attempt == 2
    assert completed_events[1].stop_reason == "passed"
    assert completed_events[0].verdicts[0]["name"] == "report_exists"


def test_store_events_captures_verification_events():
    model = ScriptedModel([_text("nope")])
    agent = Agent(model=model, verifiers=[lambda run_output: False], store_events=True)
    out = agent.run("go")
    stored = [e for e in (out.events or []) if getattr(e, "event", "") == "VerificationCompleted"]
    assert len(stored) == 3


def test_verifier_exception_fails_closed_and_run_continues():
    def boom(run_output):
        raise RuntimeError("verifier crashed")

    model = ScriptedModel([_text("try 1"), _text("try 2")])
    agent = Agent(model=model, verifiers=[boom], verification=VerificationConfig(max_attempts=2))
    out = agent.run("go")
    assert out.status == RunStatus.unverified
    assert "verifier crashed" in out.verification.attempts[0].verdicts[0].report
    assert model.calls == 2


def test_verifiers_receive_named_arguments():
    seen = {}

    def check(run_output, run_context, agent, session):
        seen["run_id"] = run_context.run_id
        seen["agent"] = agent
        seen["session"] = session
        return True

    model = ScriptedModel([_text("done")])
    a = Agent(model=model, verifiers=[check])
    out = a.run("go")
    assert seen["run_id"] == out.run_id
    assert seen["agent"] is a
    assert seen["session"] is not None


def test_output_schema_verifier_sees_parsed_content():
    from pydantic import BaseModel

    class Answer(BaseModel):
        value: int

    seen = {}

    def check(run_output):
        seen["content"] = run_output.content
        return True

    model = ScriptedModel([_text('{"value": 41}')])
    agent = Agent(model=model, verifiers=[check], output_schema=Answer)
    out = agent.run("go")
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
        verification=VerificationConfig(max_attempts=10, timeout_s=50.0),
    )
    out = agent.run("go")
    assert out.status == RunStatus.unverified
    assert out.verification.stop_reason == "timeout"
    assert len(out.verification.attempts) == 1


def test_retry_starts_with_a_fresh_record():
    calls = {"n": 0}

    class FlakyModel(ScriptedModel):
        def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return self._next()

    model = FlakyModel([_text("done")])
    agent = Agent(model=model, verifiers=[lambda run_output: True], retries=1)
    out = agent.run("go")
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 1


def test_stop_after_tool_call_still_verifies_and_reenters():
    """A tool with stop_after_tool_call=True ends the turn with content the model never
    authored; the gate still verifies that outcome and a failure re-calls the model."""
    import json as _json

    from agno.tools.decorator import tool

    @tool(stop_after_tool_call=True)
    def finish_now() -> str:
        """End the turn immediately."""
        return "tool says done"

    tool_call = ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": "call-stop",
                "type": "function",
                "function": {"name": "finish_now", "arguments": _json.dumps({})},
            }
        ],
    )
    model = ScriptedModel([tool_call, _text("model answer after the report")])
    agent = Agent(
        model=model,
        tools=[finish_now],
        verifiers=[fail_once()],
        verification=VerificationConfig(max_attempts=2),
    )
    out = agent.run("go")
    assert model.calls == 2
    assert out.status == RunStatus.completed
    assert out.verification.status == "verified"
    assert len(out.verification.attempts) == 2
