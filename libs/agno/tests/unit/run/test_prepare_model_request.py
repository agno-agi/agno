"""Offline contract tests for Agent and Team request inspection."""

from copy import deepcopy
from typing import Any, AsyncIterator, Iterator

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.exceptions import InputCheckError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import PreparedAgentModelRequest, PreparedTeamModelRequest, RunContext, RunStatus
from agno.run.agent import RunInput, RunOutput
from agno.run.cancel import get_cancellation_manager
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.tools import tool
from agno.tools.function import Function


class InspectOnlyModel(Model):
    def __init__(self):
        super().__init__(id="inspect-model", provider="test", supports_native_structured_outputs=True)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("Inspection must not invoke a model")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("Inspection must not invoke a model")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("Inspection must not invoke a model")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("Inspection must not invoke a model")
        yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class Answer(BaseModel):
    answer: str


@pytest.fixture(params=[Agent, Team], ids=["agent", "team"])
def component(request):
    options = {"members": []} if request.param is Team else {}
    return request.param(model=InspectOnlyModel(), telemetry=False, **options)


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def prepare(request, component):
    async def call(input="hello", **kwargs):
        if request.param:
            return await component.aprepare_model_request(input, **kwargs)
        return component.prepare_model_request(input, **kwargs)

    return call


@pytest.mark.asyncio
async def test_messages_tool_schema_and_context(component, prepare):
    @tool(instructions="Use echo for exact repeats.")
    def echo(text: str) -> str:
        raise AssertionError("Inspection must not execute tools")

    component.tools = [echo]
    component.instructions = "Be precise."
    component.reasoning = True
    component.reasoning_model = InspectOnlyModel()
    prepared = await prepare(
        "hello",
        session_id="session-1",
        user_id="user-1",
        run_id="run-1",
        metadata={"source": "test"},
        knowledge_filters={"topic": "testing"},
        output_schema=Answer,
    )

    expected_type = PreparedTeamModelRequest if isinstance(component, Team) else PreparedAgentModelRequest
    assert isinstance(prepared, expected_type)
    assert prepared.run_response.run_id == "run-1"
    assert prepared.run_context.user_id == "user-1"
    assert prepared.run_context.metadata == {"source": "test"}
    assert prepared.run_context.knowledge_filters == {"topic": "testing"}
    assert prepared.session.session_id == "session-1"
    assert prepared.user_message.content == "hello"
    assert "Be precise." in prepared.system_message.content
    assert prepared.messages[-1].content == "hello"
    assert prepared.response_format is Answer
    functions = [item for item in prepared.tools if isinstance(item, Function)]
    assert [item.name for item in functions] == ["echo"]
    assert functions[0].to_dict()["parameters"]["properties"]["text"]["type"] == "string"
    assert prepared.tool_instructions == ["Use echo for exact repeats."]
    assert prepared.run_response.content is None


@pytest.mark.asyncio
async def test_dependencies_pre_hooks_and_custom_arguments_are_prepared(component, prepare):
    def dependency(run_context):
        return run_context.session_state["city"]

    def pre_hook(run_input, marker):
        run_input.input_content += " " + marker

    component.dependencies = {"city": dependency}
    component.pre_hooks = [pre_hook]
    component.instructions = "City: {city}"
    context = RunContext(run_id="run-context", session_id="session-context", session_state={"city": "Paris"})
    prepared = await prepare(run_context=context, marker="prepared")
    assert prepared.run_context is context
    assert prepared.run_context.dependencies == {"city": "Paris"}
    assert prepared.user_message.content == "hello prepared"
    assert "Paris" in prepared.system_message.content
    assert callable(component.dependencies["city"])


@pytest.mark.asyncio
async def test_history_loaded_without_persisting_inspection(component, prepare):
    component.db = db = InMemoryDb()
    component.id = "component-1"
    component.add_history_to_context = True
    is_team = isinstance(component, Team)
    session_type = SessionType.TEAM if is_team else SessionType.AGENT
    session_class = TeamSession if is_team else AgentSession
    run_class = TeamRunOutput if is_team else RunOutput
    session = session_class(
        session_id="history", user_id="user-1", **{"team_id" if is_team else "agent_id": component.id}
    )
    old_run = run_class(
        run_id="old-run",
        session_id="history",
        user_id="user-1",
        status=RunStatus.completed,
        **{"team_id" if is_team else "agent_id": component.id},
        messages=[
            Message(role="user", content="Previous question"),
            Message(role="assistant", content="Previous answer"),
        ],
    )
    db.upsert_session(session)
    db.upsert_run(old_run, session_id="history")
    before = deepcopy(db.get_session(session_id="history", session_type=session_type).to_dict())
    prepared = await prepare(session_id="history", user_id="user-1")
    assert "Previous question" in [message.content for message in prepared.messages]
    assert "Previous answer" in [message.content for message in prepared.messages]
    assert db.get_session(session_id="history", session_type=session_type).to_dict() == before
    assert db.get_run(run_id=prepared.run_response.run_id) is None


@pytest.mark.asyncio
async def test_preparation_does_not_persist_introduction_or_register_run(component, prepare):
    component.db = db = InMemoryDb()
    component.introduction = "Welcome."
    prepared = await prepare(session_id="new-session", run_id="inspection")
    session_type = SessionType.TEAM if isinstance(component, Team) else SessionType.AGENT
    assert db.get_session(session_id="new-session", session_type=session_type) is None
    assert db.get_run(run_id=prepared.run_response.run_id) is None
    assert not get_cancellation_manager().cancel_run("inspection")


@pytest.mark.asyncio
async def test_preparation_failure_propagates_without_retry_or_persistence(component, prepare):
    calls = []

    def pre_hook(run_input: RunInput):
        calls.append(run_input.input_content)
        raise InputCheckError("bad input")

    component.db = db = InMemoryDb()
    component.pre_hooks = [pre_hook]
    component.retries = 2
    with pytest.raises(InputCheckError, match="bad input"):
        await prepare(session_id="failed-session")
    assert calls == ["hello"]
    session_type = SessionType.TEAM if isinstance(component, Team) else SessionType.AGENT
    assert db.get_session(session_id="failed-session", session_type=session_type) is None


@pytest.mark.asyncio
async def test_async_tool_dependency_and_hook_are_awaited(component):
    @tool(instructions="Use async echo.")
    async def echo(text: str) -> str:
        raise AssertionError("Inspection must not execute tools")

    async def dependency():
        return "Paris"

    async def pre_hook(run_input):
        run_input.input_content = "prepared async"

    component.tools = [echo]
    component.dependencies = {"city": dependency}
    component.pre_hooks = [pre_hook]
    prepared = await component.aprepare_model_request("hello")
    assert prepared.user_message.content == "prepared async"
    assert prepared.run_context.dependencies == {"city": "Paris"}
    assert [item.name for item in prepared.tools if isinstance(item, Function)] == ["echo"]
    assert prepared.tool_instructions == ["Use async echo."]


@pytest.mark.asyncio
async def test_input_validation_and_schema_override(component, prepare):
    component.input_schema = Answer
    component.output_schema = Answer
    with pytest.raises(ValueError):
        await prepare({"wrong": "field"})
    schema = {"type": "json_schema", "json_schema": {"name": "Answer", "schema": Answer.model_json_schema()}}
    prepared = await prepare({"answer": "hello"}, output_schema=schema)
    assert prepared.response_format == schema
    assert prepared.run_context.output_schema == schema
    assert component.output_schema is Answer
    assert "hello" in str(prepared.user_message.content)
    component.parser_model = InspectOnlyModel()
    assert (await prepare({"answer": "hello"})).response_format is None


@pytest.mark.asyncio
async def test_async_database_supported_without_persistence(component, tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    component.db = db = AsyncSqliteDb(db_file=str(tmp_path / "inspection.db"))
    component.introduction = "Welcome."
    with pytest.raises(RuntimeError, match="aprepare_model_request"):
        component.prepare_model_request("hello")
    prepared = await component.aprepare_model_request("hello", session_id="async-db")
    assert prepared.user_message.content == "hello"
    session_type = SessionType.TEAM if isinstance(component, Team) else SessionType.AGENT
    assert await db.get_session(session_id="async-db", session_type=session_type) is None
    await db.db_engine.dispose()


@pytest.mark.asyncio
async def test_media_and_explicit_messages_are_preserved(component, prepare):
    from agno.media import Image

    picture = Image(url="https://example.com/image.png")
    prepared = await prepare("describe", images=[picture])
    assert prepared.user_message.images[0].url == "https://example.com/image.png"
    messages = [Message(role="user", content="one")]
    prepared = await prepare(messages)
    assert [message.content for message in prepared.messages][-1:] == ["one"]
    assert [message.content for message in messages] == ["one"]


@pytest.mark.asyncio
async def test_task_mode_inspection_is_explicitly_unsupported():
    from agno.team.mode import TeamMode

    team = Team(members=[], model=InspectOnlyModel(), mode=TeamMode.tasks)
    with pytest.raises(NotImplementedError, match="task"):
        team.prepare_model_request("hello")
    with pytest.raises(NotImplementedError, match="task"):
        await team.aprepare_model_request("hello")


@pytest.mark.asyncio
async def test_inspection_does_not_cache_unpersisted_introduction(component, prepare):
    component.db = InMemoryDb()
    component.cache_session = True
    component.introduction = "Welcome."
    first = await prepare(session_id="cached-session")
    first.session.runs[0].content = "changed only in inspection"
    second = await prepare(session_id="cached-session")
    assert second.session.runs[0].content == "Welcome."


@pytest.mark.asyncio
async def test_inspection_rejects_background_tasks_but_runs_hooks_inline(component, prepare):
    from fastapi import BackgroundTasks

    from agno.hooks import hook

    calls = []

    @hook(run_in_background=True)
    def pre_hook(run_input):
        calls.append(run_input.input_content)
        run_input.input_content = "prepared inline"

    component.pre_hooks = [pre_hook]
    collector = BackgroundTasks()
    with pytest.raises(ValueError, match="background_tasks"):
        await prepare(background_tasks=collector)
    assert collector.tasks == []
    assert calls == []
    prepared = await prepare()
    assert prepared.user_message.content == "prepared inline"
    assert calls == ["hello"]
