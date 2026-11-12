"""Keyword arguments a caller passes to Agent.run that Agno does not define."""

from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunInput
from agno.run.base import RunContext, RunStatus


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


async def _run(agent: Agent, mode: str, /, **kwargs: Any) -> Any:
    """Run the agent in one of the four run shapes and return the final RunOutput."""
    if mode == "sync":
        return agent.run("hi", **kwargs)
    if mode == "async":
        return await agent.arun("hi", **kwargs)
    if mode == "sync-stream":
        events = list(agent.run("hi", stream=True, yield_run_output=True, **kwargs))
        return events[-1]
    events = [event async for event in agent.arun("hi", stream=True, yield_run_output=True, **kwargs)]
    return events[-1]


MODES = ["sync", "async", "sync-stream", "async-stream"]

# Names the run pipeline binds internally; an extra kwarg with one of these names used to crash the run
INTERNAL_NAMES = ["agent", "session", "run_input", "run_response", "run_messages", "hooks", "tools", "response_format"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", INTERNAL_NAMES)
async def test_extra_kwarg_named_like_an_internal_argument_does_not_break_the_run(mode, name):
    agent = Agent(model=RecordingModel(), pre_hooks=[lambda run_input: None], telemetry=False)

    result = await _run(agent, mode, **{name: "from-caller"})

    assert result.status == RunStatus.completed
    assert result.content == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_extra_kwargs_reach_a_pre_hook_and_framework_arguments_win(mode):
    seen: Dict[str, Any] = {}

    def guard(run_input: RunInput, agent: Agent, tenant: Optional[str] = None) -> None:
        seen.update(tenant=tenant, agent=agent, input=run_input.input_content)

    agent = Agent(model=RecordingModel(), pre_hooks=[guard], telemetry=False)

    await _run(agent, mode, tenant="acme", agent="spoofed")

    assert seen["tenant"] == "acme"
    assert seen["agent"] is agent
    assert seen["input"] == "hi"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_extra_kwargs_do_not_become_user_message_fields(mode):
    model = RecordingModel()
    agent = Agent(model=model, telemetry=False)

    await _run(agent, mode, name="spoofed-name", tenant="acme")

    user_message = [m for m in model.sent[-1] if m.role == "user"][-1]
    assert user_message.name is None
    assert "tenant" not in (user_message.model_extra or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_extra_kwargs_are_on_the_run_context(mode):
    contexts: List[RunContext] = []

    def capture(run_context: RunContext) -> None:
        contexts.append(run_context)

    agent = Agent(model=RecordingModel(), pre_hooks=[capture], telemetry=False)

    await _run(agent, mode, tenant="acme")

    assert contexts[-1].extra_kwargs == {"tenant": "acme"}


def test_extra_kwargs_replace_those_on_a_passed_run_context_and_keep_them_when_none_are_passed():
    contexts: List[RunContext] = []
    agent = Agent(model=RecordingModel(), pre_hooks=[lambda run_context: contexts.append(run_context)], telemetry=False)
    run_context = RunContext(run_id="r1", session_id="s1", extra_kwargs={"tenant": "old"})

    agent.run("hi", run_context=run_context)
    assert contexts[-1].extra_kwargs == {"tenant": "old"}

    agent.run("hi", run_context=run_context, tenant="new")
    assert contexts[-1].extra_kwargs == {"tenant": "new"}


def _retriever_agent(retriever: Any) -> Agent:
    return Agent(
        model=RecordingModel(),
        knowledge_retriever=retriever,
        add_knowledge_to_context=True,
        search_knowledge=False,
        telemetry=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_retriever_without_var_kwargs_still_runs_when_extras_are_sent(mode):
    calls: List[str] = []

    def retriever(query: str, num_documents: Optional[int] = None) -> List[Dict[str, Any]]:
        calls.append(query)
        return [{"content": "doc"}]

    result = await _run(_retriever_agent(retriever), mode, tenant="acme")

    assert calls == ["hi"]
    assert result.references and result.references[0].references == [{"content": "doc"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_retriever_gets_declared_extras_but_not_overrides_of_its_inputs(mode):
    seen: Dict[str, Any] = {}

    def retriever(query: str, num_documents: Optional[int] = None, tenant: Optional[str] = None, **kwargs: Any):
        seen.update(query=query, tenant=tenant, num_documents=num_documents)
        return [{"content": "doc"}]

    await _run(_retriever_agent(retriever), mode, tenant="acme", query="injected", num_documents=999)

    assert seen["tenant"] == "acme"
    assert seen["query"] == "hi"
    assert seen["num_documents"] != 999


def test_direct_retriever_call_kwargs_still_reach_the_retriever():
    seen: Dict[str, Any] = {}

    def retriever(query: str, num_documents: Optional[int] = None, tenant: Optional[str] = None):
        seen.update(tenant=tenant)
        return [{"content": "doc"}]

    agent = _retriever_agent(retriever)

    agent.get_relevant_docs_from_knowledge("q", tenant="acme")

    assert seen["tenant"] == "acme"
