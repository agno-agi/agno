import pytest
from pydantic import ValidationError

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team


def _delegate_tool(team: Team, *, async_mode: bool = False, run_context: RunContext | None = None):
    team.initialize_team()
    run_context = run_context or RunContext(session_state={}, run_id="run", session_id="session")
    tools = team._determine_tools_for_model(
        model=team.model,
        run_response=TeamRunOutput(run_id="run"),
        run_context=run_context,
        team_run_context={},
        session=TeamSession(session_id="session", team_id=team.id),
        async_mode=async_mode,
    )
    return next(tool for tool in tools if tool.name == "delegate_task_to_member")


@pytest.mark.parametrize("async_mode", [False, True])
def test_delegate_member_id_schema_uses_current_members(async_mode):
    team = Team(
        id="team",
        model=OpenAIChat("gpt-5.6-luna"),
        members=[
            Agent(id="researcher", name="Researcher", role="Find primary sources"),
            Agent(id="writer", name="Writer", role="Write the response"),
        ],
    )

    tool = _delegate_tool(team, async_mode=async_mode)
    member_schema = tool.parameters["properties"]["member_id"]

    assert member_schema["enum"] == ["researcher", "writer"]
    assert "researcher: Find primary sources" in member_schema["description"]
    assert "writer: Write the response" in member_schema["description"]


def test_delegate_member_id_validation_rejects_unknown_member():
    team = Team(
        id="team",
        model=OpenAIChat("gpt-5.6-luna"),
        members=[Agent(id="researcher", name="Researcher")],
    )
    tool = _delegate_tool(team)

    with pytest.raises(ValidationError, match="researcher"):
        next(tool.entrypoint(member_id="unknown", task="Research the topic"))


def test_delegate_member_id_schema_tracks_callable_members_per_run():
    def members(run_context: RunContext):
        return [Agent(id=run_context.user_id, name="Assigned member")]

    team = Team(id="team", model=OpenAIChat("gpt-5.6-luna"), members=members, cache_callables=False)

    first = _delegate_tool(
        team,
        run_context=RunContext(session_state={}, run_id="first", session_id="session", user_id="alpha"),
    )
    second = _delegate_tool(
        team,
        run_context=RunContext(session_state={}, run_id="second", session_id="session", user_id="beta"),
    )

    assert first.parameters["properties"]["member_id"]["enum"] == ["alpha"]
    assert second.parameters["properties"]["member_id"]["enum"] == ["beta"]
