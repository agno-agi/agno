"""A guardrail in the hooks must run on a continued run.

A component that continues a paused run has often never started one: AgentOS
serves each request from a fresh copy. Its hooks then still hold the guardrail
objects, not the callables the hook runner expects.
"""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.guardrails.base import BaseGuardrail
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.requirement import RunRequirement
from agno.team import Team
from agno.tools import tool


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        from agno.metrics import MessageMetrics

        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
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

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


class _RecordingGuardrail(BaseGuardrail):
    """Records the output of every run it checks."""

    def __init__(self) -> None:
        self.checked: List[Any] = []

    def check(self, run_input: Any = None, run_output: Any = None) -> None:
        self.checked.append(getattr(run_output, "content", None))

    async def async_check(self, run_input: Any = None, run_output: Any = None) -> None:
        self.check(run_input, run_output)


@tool(requires_confirmation=True)
def gated() -> str:
    """A tool that pauses the run for confirmation."""
    return "ran"


def _component(kind: str, db: SqliteDb, guardrail: BaseGuardrail, script: List[tuple]):
    model = _ScriptedModel(f"m-{kind}", script)
    if kind == "agent":
        return Agent(id="guarded", model=model, tools=[gated], db=db, post_hooks=[guardrail], telemetry=False)
    member = Agent(id="bystander", name="Bystander", model=_ScriptedModel("m-member", [("content", "hi")]))
    return Team(
        id="guarded", model=model, members=[member], tools=[gated], db=db, post_hooks=[guardrail], telemetry=False
    )


def _confirmed(requirements) -> List[RunRequirement]:
    """Round-trip requirements through their wire format and confirm them, as a client would."""
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        req.confirm()
        confirmed.append(req)
    return confirmed


@pytest.fixture
def hook_errors(monkeypatch) -> List[str]:
    """Every failure the hook runners log, for Agent and for Team."""
    errors: List[str] = []
    for module in ("agno.agent._hooks", "agno.team._hooks"):
        monkeypatch.setattr(f"{module}.log_exception", lambda message, *a, **k: errors.append(message))
    return errors


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
async def test_guardrail_runs_on_a_continued_run(tmp_path, hook_errors, kind, use_async, stream):
    db = SqliteDb(db_file=str(tmp_path / "guardrail.db"))

    paused = _component(kind, db, _RecordingGuardrail(), [("tool", "gated", {}, "tc-1")]).run("go", session_id="s")
    assert paused.is_paused, "the gated tool should pause the first run"

    # The continuing component has never started a run, as a served copy has not.
    guardrail = _RecordingGuardrail()
    component = _component(kind, db, guardrail, [("content", "done")])
    kwargs = dict(run_id=paused.run_id, session_id="s", requirements=_confirmed(paused.requirements))

    if stream and use_async:
        events = [event async for event in component.acontinue_run(stream=True, yield_run_output=True, **kwargs)]
        result = events[-1]
    elif stream:
        result = list(component.continue_run(stream=True, yield_run_output=True, **kwargs))[-1]
    elif use_async:
        result = await component.acontinue_run(**kwargs)
    else:
        result = component.continue_run(**kwargs)

    assert result.status.value == "COMPLETED"
    assert hook_errors == []
    assert guardrail.checked == ["done"], "the guardrail did not check the continued run"
