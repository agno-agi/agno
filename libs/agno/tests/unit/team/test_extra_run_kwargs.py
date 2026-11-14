"""Keyword arguments a caller passes to Team.run that Agno does not define."""

from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import pytest

from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.run.base import RunContext, RunStatus
from agno.run.team import TeamRunInput
from agno.team.team import Team


class RecordingModel(Model):
    """Offline model that records the messages it was sent."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self.sent: List[List[Message]] = []

    def _reply(self, args: Any, kwargs: Dict[str, Any]) -> ModelResponse:
        self.sent.append(list(kwargs.get("messages") or args[0]))
        return ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._reply(args, kwargs)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._reply(args, kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._reply(args, kwargs)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._reply(args, kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


async def _run(team: Team, mode: str, /, **kwargs: Any) -> Any:
    """Run the team in one of the four run shapes and return the final TeamRunOutput."""
    if mode == "sync":
        return team.run("hi", **kwargs)
    if mode == "async":
        return await team.arun("hi", **kwargs)
    if mode == "sync-stream":
        events = list(team.run("hi", stream=True, yield_run_output=True, **kwargs))
        return events[-1]
    events = [event async for event in team.arun("hi", stream=True, yield_run_output=True, **kwargs)]
    return events[-1]


MODES = ["sync", "async", "sync-stream", "async-stream"]

# Names the run pipeline binds internally; an extra kwarg with one of these names used to crash the run
INTERNAL_NAMES = ["team", "session", "run_input", "run_response", "run_messages", "hooks", "tools", "response_format"]


def _team(**kwargs: Any) -> Team:
    return Team(members=[], model=RecordingModel(), telemetry=False, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", INTERNAL_NAMES)
async def test_extra_kwarg_named_like_an_internal_argument_does_not_break_the_run(mode, name):
    team = _team(pre_hooks=[lambda run_input: None])

    result = await _run(team, mode, **{name: "from-caller"})

    assert result.status == RunStatus.completed
    assert result.content == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_extra_kwargs_reach_a_pre_hook_and_framework_arguments_win(mode):
    seen: Dict[str, Any] = {}

    def guard(run_input: TeamRunInput, team: Team, tenant: Optional[str] = None) -> None:
        seen.update(tenant=tenant, team=team)

    team = _team(pre_hooks=[guard])

    await _run(team, mode, tenant="acme", team="spoofed")

    assert seen["tenant"] == "acme"
    assert seen["team"] is team


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_extra_kwargs_do_not_become_user_message_fields(mode):
    team = _team()

    await _run(team, mode, name="spoofed-name", tenant="acme")

    user_message = [m for m in team.model.sent[-1] if m.role == "user"][-1]  # type: ignore[union-attr]
    assert user_message.name is None
    assert "tenant" not in (user_message.model_extra or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_extra_kwargs_are_on_the_run_context(mode):
    contexts: List[RunContext] = []
    team = _team(pre_hooks=[lambda run_context: contexts.append(run_context)])

    await _run(team, mode, tenant="acme")

    assert contexts[-1].extra_kwargs == {"tenant": "acme"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_retriever_gets_declared_extras_but_not_overrides_of_its_inputs(mode):
    seen: Dict[str, Any] = {}

    def retriever(query: str, num_documents: Optional[int] = None, tenant: Optional[str] = None):
        seen.update(query=query, tenant=tenant, num_documents=num_documents)
        return [{"content": "doc"}]

    team = _team(knowledge_retriever=retriever, add_knowledge_to_context=True, search_knowledge=False)

    await _run(team, mode, tenant="acme", query="injected", num_documents=999, other="dropped")

    assert seen["tenant"] == "acme"
    assert seen["query"] == "hi"
    assert seen["num_documents"] != 999
