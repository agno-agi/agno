import json
from typing import List

import pytest

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import _default_tools
from agno.team.team import Team


def _team_run(index: int) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=f"run-{index}",
        session_id="s1",
        team_id="team-1",
        messages=[
            Message(role="system", content="You lead the team."),
            Message(role="user", content=f"Q{index}"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {"id": "call-1", "type": "function", "function": {"name": "delegate_task", "arguments": "{}"}}
                ],
            ),
            Message(role="tool", content="member output", tool_call_id="call-1"),
            Message(role="assistant", content=f"A{index}"),
        ],
    )


def _member_run(index: int) -> RunOutput:
    return RunOutput(
        run_id=f"member-run-{index}",
        parent_run_id=f"run-{index}",
        session_id="s1",
        agent_id="member-1",
        messages=[Message(role="user", content="task"), Message(role="assistant", content="member answer")],
    )


def _session() -> TeamSession:
    return TeamSession(
        session_id="s1",
        team_id="team-1",
        runs=[_team_run(1), _member_run(1), _team_run(2), _member_run(2)],
    )


def _turns(result: str) -> List[tuple]:
    return [(m["role"], m["content"]) for m in json.loads(result)]


@pytest.fixture
def team() -> Team:
    return Team(id="team-1", members=[])


def test_last_chat_is_one_user_team_exchange(team):
    tool = _default_tools._get_chat_history_function(team, _session())
    assert _turns(tool.entrypoint(num_chats=1)) == [("user", "Q2"), ("assistant", "A2")]  # type: ignore[misc]


def test_all_chats_skip_member_runs_and_tool_messages(team):
    tool = _default_tools._get_chat_history_function(team, _session())
    assert _turns(tool.entrypoint()) == [  # type: ignore[misc]
        ("user", "Q1"),
        ("assistant", "A1"),
        ("user", "Q2"),
        ("assistant", "A2"),
    ]


@pytest.mark.asyncio
async def test_async_last_chat_is_one_user_team_exchange(team):
    tool = _default_tools._get_chat_history_function(team, _session(), async_mode=True)
    assert _turns(await tool.entrypoint(num_chats=1)) == [("user", "Q2"), ("assistant", "A2")]  # type: ignore[misc]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_empty_session_returns_empty_json_list(team, async_mode):
    tool = _default_tools._get_chat_history_function(team, TeamSession(session_id="s1"), async_mode=async_mode)
    result = tool.entrypoint(num_chats=0)  # type: ignore[misc]
    if async_mode:
        result = await result
    assert json.loads(result) == []
