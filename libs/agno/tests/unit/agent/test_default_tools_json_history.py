import json
from typing import Any, Optional

import pytest

from agno.agent import _default_tools
from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.session import AgentSession


class _EmptySessionsDb:
    def get_sessions(
        self,
        session_type: SessionType,
        limit: Optional[int] = None,
        user_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> list[Any]:
        return []


@pytest.mark.parametrize("db", [None, _EmptySessionsDb()])
def test_get_previous_sessions_messages_returns_valid_json_when_empty(db):
    agent = Agent(name="test-agent", db=db)
    get_previous_session_messages = _default_tools.get_previous_sessions_messages_function(agent)

    result = get_previous_session_messages()
    assert json.loads(result) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("db", [None, _EmptySessionsDb()])
async def test_aget_previous_sessions_messages_returns_valid_json_when_empty(db):
    agent = Agent(name="test-agent", db=db)
    get_previous_session_messages_function = await _default_tools.aget_previous_sessions_messages_function(agent)

    result = await get_previous_session_messages_function.entrypoint()  # type: ignore[misc]
    assert json.loads(result) == []


def test_get_chat_history_returns_valid_json_when_empty():
    agent = Agent(name="test-agent")
    session = AgentSession(session_id="session-1")

    get_chat_history = _default_tools.get_chat_history_function(agent, session)
    result = get_chat_history()

    assert json.loads(result) == []


def test_get_tool_call_history_returns_valid_json_when_empty():
    agent = Agent(name="test-agent")
    session = AgentSession(session_id="session-1")

    get_tool_call_history = _default_tools.get_tool_call_history_function(agent, session)
    result = get_tool_call_history()

    assert json.loads(result) == []
