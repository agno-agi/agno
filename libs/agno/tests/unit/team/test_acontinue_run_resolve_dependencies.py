"""Team async continue paths must resolve callable dependencies after fork.

`team.run()` / `team.arun()` and the sync `continue_run` dispatch resolve
callable factories on `run_context.dependencies`. `_acontinue_run` and
`_acontinue_run_stream` must do the same, and they must do it *after*
`_apply_continue_modifiers_team` so a factory that reads `run_context`
sees the forked run. Resolving inside `_asetup_session` first consumes
every factory against the parent run id.
"""

from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunContext
from agno.team import Team
from agno.team import _run as team_run


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


def _tool_call(name: str, call_id: str) -> ModelResponse:
    import json

    return ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({})},
            }
        ],
    )


def _token_factory() -> str:
    return "resolved-token"


def _dependency_probe(seen: List[Any]):
    def probe_state(run_context: Optional[RunContext] = None) -> str:
        """Record the dependency value the continuation handed the tool."""
        deps = (run_context.dependencies or {}) if run_context else {}
        seen.append(deps.get("token"))
        return "probed"

    return probe_state


def _probe_script() -> List[ModelResponse]:
    return [
        _tool_call("probe_state", "call-1"),
        _text("first run done"),
        _tool_call("probe_state", "call-2"),
        _text("continuation done"),
    ]


def _make_team(seen: List[Any], factory) -> Team:
    member = Agent(name="member", model=ScriptedModel([_text("member done")]))
    return Team(
        members=[member],
        model=ScriptedModel(_probe_script()),
        tools=[_dependency_probe(seen)],
        dependencies={"token": factory},
    )


def _track_apply_vs_factory(monkeypatch, order: List[str], factory):
    original_apply = team_run._apply_continue_modifiers_team

    def tracking_apply(*args, **kwargs):
        order.append("apply")
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(team_run, "_apply_continue_modifiers_team", tracking_apply)

    def tracked_factory(*args, **kwargs):
        order.append("factory")
        return factory(*args, **kwargs)

    return tracked_factory


def _assert_resolved_after_apply(order: List[str], seen: List[Any], *, path: str) -> None:
    assert "apply" in order, f"{path} never applied continue modifiers"
    assert "factory" in order, f"{path} never invoked the dependency factory"
    assert order.index("apply") < order.index("factory"), (
        f"{path} resolved the factory before _apply_continue_modifiers_team: {order}"
    )
    assert not callable(seen[-1]), f"{path} left the factory unresolved: {seen[-1]}"
    assert seen[-1] == "resolved-token"
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_acontinue_run_resolves_callable_dependencies(monkeypatch):
    """An async continuation must invoke the factory after continue modifiers."""
    seen: List[Any] = []
    order: List[str] = []
    factory = _track_apply_vs_factory(monkeypatch, order, _token_factory)
    team = _make_team(seen, factory)
    first = await team.arun("probe once")
    order.clear()
    continued = await team.acontinue_run(run_response=first, input="probe again")
    assert continued is not None
    _assert_resolved_after_apply(order, seen, path="acontinue_run")


@pytest.mark.asyncio
async def test_acontinue_run_stream_resolves_callable_dependencies(monkeypatch):
    """Streaming async continuation must resolve factories after continue modifiers too."""
    seen: List[Any] = []
    order: List[str] = []
    factory = _track_apply_vs_factory(monkeypatch, order, _token_factory)
    team = _make_team(seen, factory)
    first = await team.arun("probe once")
    order.clear()
    events = []
    async for event in team.acontinue_run(run_response=first, input="probe again", stream=True):
        events.append(event)
    assert events
    _assert_resolved_after_apply(order, seen, path="acontinue_run_stream")
