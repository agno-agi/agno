import json
from typing import List, Optional

import pytest

from agno.agent import _default_tools
from agno.agent.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


def _run(
    index: int,
    tool_call: bool = False,
    history: Optional[List[Message]] = None,
    status: RunStatus = RunStatus.completed,
) -> RunOutput:
    messages = [Message(role="system", content="You are helpful.")]
    messages += history or []
    messages.append(Message(role="user", content=f"Q{index}"))
    if tool_call:
        messages.append(
            Message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
            )
        )
        messages.append(Message(role="tool", content="raw tool output", tool_call_id="call-1"))
    messages.append(Message(role="assistant", content=f"A{index}"))
    return RunOutput(run_id=f"run-{index}", session_id="s1", agent_id="agent-1", messages=messages, status=status)


def _history(*indexes: int) -> List[Message]:
    msgs = []
    for i in indexes:
        msgs.append(Message(role="user", content=f"Q{i}", from_history=True))
        msgs.append(Message(role="assistant", content=f"A{i}", from_history=True))
    return msgs


@pytest.fixture
def get_chat_history():
    session = AgentSession(
        session_id="s1",
        agent_id="agent-1",
        runs=[
            _run(1),
            _run(2, tool_call=True, history=_history(1)),
            _run(99, status=RunStatus.error),
            _run(3, history=_history(1, 2)),
        ],
    )
    return _default_tools.get_chat_history_function(Agent(id="agent-1"), session)


def _turns(result: str) -> List[tuple]:
    return [(m["role"], m["content"]) for m in json.loads(result)]


def test_last_chat_is_one_user_assistant_exchange(get_chat_history):
    assert _turns(get_chat_history(num_chats=1)) == [("user", "Q3"), ("assistant", "A3")]


def test_chats_counted_per_run_without_tool_or_system_messages(get_chat_history):
    assert _turns(get_chat_history(num_chats=2)) == [
        ("user", "Q2"),
        ("assistant", "A2"),
        ("user", "Q3"),
        ("assistant", "A3"),
    ]


def test_all_chats_oldest_first_without_history_duplicates_or_failed_runs(get_chat_history):
    expected = [
        ("user", "Q1"),
        ("assistant", "A1"),
        ("user", "Q2"),
        ("assistant", "A2"),
        ("user", "Q3"),
        ("assistant", "A3"),
    ]
    assert _turns(get_chat_history()) == expected
    assert _turns(get_chat_history(num_chats=10)) == expected


@pytest.mark.parametrize("num_chats", [0, -1])
def test_non_positive_num_chats_returns_nothing(get_chat_history, num_chats):
    assert json.loads(get_chat_history(num_chats=num_chats)) == []
