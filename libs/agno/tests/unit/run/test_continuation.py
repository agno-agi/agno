"""Background continuation history, with foreground compatibility coverage."""

from copy import deepcopy

import pytest

from agno.agent import Agent
from agno.agent._messages import _build_continue_run_messages as agent_messages
from agno.db.base import SessionType
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ToolExecution
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.team._run import _build_continue_run_messages as team_messages
from agno.tools import tool
from agno.tools.function import UserInputField


class InspectModel(Model):
    def __init__(self, inspect_messages):
        super().__init__(id="offline", provider="test")
        self.inspect_messages = inspect_messages
        self.calls = 0
        self.requests = []

    def invoke(self, messages, **kwargs):
        self.calls += 1
        self.requests.append(list(messages))
        self.inspect_messages(messages)
        return ModelResponse(role="assistant", content="done")

    async def ainvoke(self, messages, **kwargs):
        return self.invoke(messages, **kwargs)

    def invoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.fixture(params=["agent", "team"])
def kind(request):
    return request.param


def make_component(kind, **kwargs):
    if kind == "agent":
        return Agent(id="component", telemetry=False, **kwargs)
    return Team(id="component", members=[], telemetry=False, **kwargs)


def make_run(kind, run_id, **kwargs):
    cls = RunOutput if kind == "agent" else TeamRunOutput
    return cls(run_id=run_id, session_id="session", user_id="owner", **{kind + "_id": "component"}, **kwargs)


def make_session(kind, runs):
    cls = AgentSession if kind == "agent" else TeamSession
    return cls(session_id="session", user_id="owner", runs=runs, **{kind + "_id": "component"})


@pytest.mark.parametrize("status", list(RunStatus))
@pytest.mark.parametrize("fork_depth", [0, 2])
def test_history_excludes_current_transcript_before_limits(kind, status, fork_depth):
    component = make_component(kind, add_history_to_context=True, num_history_runs=1)
    prior = make_run(kind, "prior", status=RunStatus.completed, messages=[Message(role="user", content="prior")])
    source = make_run(kind, "source", status=status, messages=[Message(role="user", content="current")])
    runs = [prior, source]
    current = source
    for index in range(fork_depth):
        current = make_run(
            kind,
            f"fork-{index}",
            status=status,
            messages=deepcopy(source.messages),
            forked_from_run_id=current.run_id,
        )
        runs.append(current)
    session = make_session(kind, runs)
    before = deepcopy(session.to_dict())
    builder = agent_messages if kind == "agent" else team_messages
    result = builder(component, input=deepcopy(current.messages), session=session, run_response=current)
    assert [m.content for m in result.messages] == ["prior", "current"]
    assert session.to_dict() == before


def prepare_continuation(kind, tmp_path, pause_type, expected_status=RunStatus.paused):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    tool_calls = []

    @tool(
        external_execution=pause_type == "external",
        requires_confirmation=pause_type == "confirmation",
        requires_user_input=pause_type == "user_input",
        user_input_fields=["city"] if pause_type == "user_input" else None,
    )
    def location(city: str) -> str:
        """Return a city after approval or user input."""
        assert db.get_run("current").status == expected_status
        tool_calls.append(city)
        return city

    execution = ToolExecution(
        tool_call_id="call-location",
        tool_name="location",
        tool_args={"city": "Paris"},
        external_execution_required=pause_type == "external",
        requires_confirmation=pause_type == "confirmation",
        requires_user_input=pause_type == "user_input",
        user_input_schema=[UserInputField(name="city", field_type=str)] if pause_type == "user_input" else None,
    )
    requirement = RunRequirement(tool_execution=execution)
    current = make_run(
        kind,
        "current",
        status=RunStatus.paused,
        messages=[
            Message(role="user", content="current request"),
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": execution.tool_call_id,
                        "type": "function",
                        "function": {"name": "location", "arguments": '{"city":"Paris"}'},
                    }
                ],
            ),
        ],
        tools=[execution],
        requirements=[requirement],
    )
    prior = make_run(kind, "prior", status=RunStatus.completed, messages=[Message(role="user", content="prior")])
    session = make_session(kind, [prior, current])
    db.upsert_session(session)
    for index, run in enumerate(session.runs):
        db.upsert_run(run, session_id=session.session_id, user_id="owner", run_index=index)

    def inspect_messages(messages):
        assert db.get_run("current").status == expected_status
        assert sum(m.content == "prior" for m in messages) == 1
        assert sum(m.content == "current request" for m in messages) == 1
        assert sum(bool(m.tool_calls) for m in messages) == 1
        assert sum(m.tool_call_id == "call-location" for m in messages) == 1

    model = InspectModel(inspect_messages)
    component = make_component(
        kind, model=model, tools=[location], db=db, add_history_to_context=True, num_history_runs=1
    )
    if pause_type == "external":
        requirement.set_external_execution_result("Paris")
    elif pause_type == "confirmation":
        requirement.confirm()
    else:
        requirement.provide_user_input({"city": "Paris"})
    return component, current, model, tool_calls


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("by_id", [False, True])
@pytest.mark.parametrize("pause_type", ["external", "confirmation", "user_input"])
def test_sync_continue_preserves_status_behavior_and_pairs_tools(kind, tmp_path, stream, by_id, pause_type):
    component, current, model, calls = prepare_continuation(kind, tmp_path, pause_type)
    args = {"run_id": current.run_id, "requirements": current.requirements} if by_id else {"run_response": current}
    result = component.continue_run(session_id="session", stream=stream, **args)
    if stream:
        list(result)
    assert model.calls == 1
    assert component.db.get_run("current").status == RunStatus.completed
    assert calls == ([] if pause_type == "external" else ["Paris"])


@pytest.mark.asyncio
@pytest.mark.parametrize("stream,background", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("by_id", [False, True])
@pytest.mark.parametrize("pause_type", ["external", "confirmation", "user_input"])
@pytest.mark.parametrize("async_db", [False, True])
async def test_async_continue_preserves_status_behavior_and_pairs_tools(
    kind, tmp_path, stream, background, by_id, pause_type, async_db
):
    component, current, model, calls = prepare_continuation(
        kind, tmp_path, pause_type, expected_status=RunStatus.running if stream and background else RunStatus.paused
    )
    reader = component.db
    if async_db:
        component.db = AsyncSqliteDb(db_file=str(tmp_path / "runs.db"))
    args = {"run_id": current.run_id, "requirements": current.requirements} if by_id else {"run_response": current}
    result = component.acontinue_run(session_id="session", stream=stream, background=background, **args)
    if stream:
        async for _ in result:
            pass
    else:
        await result
    assert model.calls == 1
    assert reader.get_run("current").status == RunStatus.completed
    assert calls == ([] if pause_type == "external" else ["Paris"])


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_completed_continue_excludes_fork_source_from_history(kind, tmp_path, asynchronous, stream):
    component, current, model, _ = prepare_continuation(kind, tmp_path, "external")
    current.status = RunStatus.completed
    current.tools = None
    current.requirements = None
    current.messages = [
        Message(role="user", content="source request"),
        Message(role="assistant", content="source answer"),
    ]
    component.db.upsert_run(current, session_id="session", user_id="owner")
    source_before = component.db.get_run("current").to_dict()

    model.inspect_messages = lambda messages: None
    method = component.acontinue_run if asynchronous else component.continue_run
    result = method(run_id="current", session_id="session", stream=stream)
    if asynchronous:
        if stream:
            async for _ in result:
                pass
        else:
            await result
    elif stream:
        list(result)
    assert model.calls == 1
    messages = model.requests[-1]
    assert sum(m.content == "source request" for m in messages) == 1
    assert sum(m.content == "source answer" for m in messages) == 1
    assert sum(m.content == "prior" for m in messages) == 1
    assert component.db.get_run("current").to_dict() == source_before


def build_history(kind, runs, current, **component_kwargs):
    component = make_component(kind, add_history_to_context=True, **component_kwargs)
    builder = agent_messages if kind == "agent" else team_messages
    session = make_session(kind, runs)
    result = builder(component, input=deepcopy(current.messages), session=session, run_response=current)
    return [m.content for m in result.messages]


def text_run(kind, run_id, *contents, status=RunStatus.completed, forked_from=None):
    return make_run(
        kind,
        run_id,
        status=status,
        messages=[Message(role="user", content=c) for c in contents],
        forked_from_run_id=forked_from,
    )


def test_resuming_original_excludes_its_completed_fork(kind):
    """Resuming a paused run must not read back a fork of it, which copies the same turns."""
    prior = text_run(kind, "prior", "prior")
    original = text_run(kind, "original", "current", status=RunStatus.paused)
    fork = text_run(kind, "fork", "current", "fork turn", forked_from="original")
    assert build_history(kind, [prior, original, fork], original) == ["prior", "current"]


def test_continuing_a_fork_excludes_sibling_forks(kind):
    prior = text_run(kind, "prior", "prior")
    source = text_run(kind, "source", "current")
    first_fork = text_run(kind, "fork-1", "current", "first branch", forked_from="source")
    second_fork = text_run(kind, "fork-2", "current", status=RunStatus.paused, forked_from="source")
    runs = [prior, source, first_fork, second_fork]
    assert build_history(kind, runs, second_fork) == ["prior", "current"]


def test_get_messages_keeps_only_the_latest_run_of_a_fork_tree(kind):
    """Normal runs read history through get_messages, so fork sources must not repeat there either."""
    prior = text_run(kind, "prior", "prior")
    source = text_run(kind, "source", "question")
    fork = text_run(kind, "fork", "question", "follow up", forked_from="source")
    session = make_session(kind, [prior, source, fork])
    assert [m.content for m in session.get_messages()] == ["prior", "question", "follow up"]
    assert [m.content for m in session.get_messages(last_n_runs=1)] == ["question", "follow up"]


def test_get_messages_keeps_the_source_while_its_fork_is_skipped(kind):
    """A fork that paused or failed does not replace its source in history."""
    source = text_run(kind, "source", "question")
    fork = text_run(kind, "fork", "question", "follow up", status=RunStatus.paused, forked_from="source")
    session = make_session(kind, [source, fork])
    assert [m.content for m in session.get_messages()] == ["question"]


def test_get_messages_without_forks_is_unchanged(kind):
    runs = [text_run(kind, f"run-{i}", f"turn {i}") for i in range(3)]
    session = make_session(kind, runs)
    assert [m.content for m in session.get_messages()] == ["turn 0", "turn 1", "turn 2"]


@pytest.mark.asyncio
async def test_new_run_after_auto_fork_sees_the_source_turn_once(kind, tmp_path):
    """Continuing a COMPLETED run with input forks it; the next run must not see the shared turn twice."""
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    model = InspectModel(lambda messages: None)
    component = make_component(kind, model=model, db=db, add_history_to_context=True)
    source = make_run(
        kind,
        "source",
        status=RunStatus.completed,
        messages=[Message(role="user", content="source request"), Message(role="assistant", content="source answer")],
    )
    session = make_session(kind, [source])
    db.upsert_session(session)
    db.upsert_run(source, session_id="session", user_id="owner", run_index=0)

    await component.acontinue_run(run_id="source", session_id="session", user_id="owner", input="follow up")
    await component.arun("new message", session_id="session", user_id="owner")

    messages = model.requests[-1]
    assert sum(m.content == "source request" for m in messages) == 1, [m.content for m in messages]
    assert sum(m.content == "follow up" for m in messages) == 1, [m.content for m in messages]


def test_team_history_context_shows_a_forked_turn_once():
    """Members get team history as [run-N] entries, which must not repeat a fork's source run."""

    def team_turn(run_id, question, answer, forked_from=None):
        return make_run(
            "team",
            run_id,
            status=RunStatus.completed,
            input=TeamRunInput(input_content=question),
            content=answer,
            forked_from_run_id=forked_from,
        )

    session = make_session(
        "team",
        [
            team_turn("prior", "What is the capital of France?", "Paris"),
            team_turn("source", "What is the capital of Portugal?", "Lisbon"),
            team_turn("fork", "What is the capital of Portugal?", "Lisbon", forked_from="source"),
        ],
    )
    assert session.get_team_history() == [
        ("What is the capital of France?", "Paris"),
        ("What is the capital of Portugal?", "Lisbon"),
    ]
    assert "[run-3]" not in (session.get_team_history_context() or "")
    assert session.get_team_history(num_runs=1) == [("What is the capital of Portugal?", "Lisbon")]


def save_runs(db, kind, runs):
    db.upsert_session(make_session(kind, runs))
    for index, run in enumerate(runs):
        db.upsert_run(run, session_id="session", user_id="owner", run_index=index)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_bounded_session_messages_match_full_history_with_forks(tmp_path, asynchronous):
    """The "most recent N" read must return the same window as get_messages on the full session."""
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    save_runs(
        db,
        "agent",
        [
            text_run("agent", "name", "My name is Harsh."),
            text_run("agent", "city", "My city is Pune."),
            text_run("agent", "fork", "My city is Pune.", "Reply only DONE.", forked_from="city"),
        ],
    )
    agent = Agent(id="component", db=db, telemetry=False)
    full_session = db.get_session(session_id="session", session_type=SessionType.AGENT, user_id="owner")
    expected = [m.content for m in full_session.get_messages(last_n_runs=2)]

    if asynchronous:
        bounded = await agent.aget_session_messages(session_id="session", last_n_runs=2)
    else:
        bounded = agent.get_session_messages(session_id="session", last_n_runs=2)

    assert expected == ["My name is Harsh.", "My city is Pune.", "Reply only DONE."]
    assert [m.content for m in bounded] == expected
