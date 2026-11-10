import json
from datetime import datetime
from typing import Any, Optional

import pytest

from agno.agent import _default_tools
from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.message import Message
from agno.run.agent import RunOutput
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

    def get_session(
        self,
        session_id: str = "",
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Any]:
        return None


def _make_session(
    session_id: str, messages: list[tuple[str, str]], created_at: Optional[datetime] = None
) -> AgentSession:
    """Helper to build an AgentSession with user/assistant message pairs."""
    msgs = []
    for user_text, assistant_text in messages:
        msgs.append(Message(role="user", content=user_text))
        msgs.append(Message(role="assistant", content=assistant_text))

    run = RunOutput(
        run_id="run-1",
        session_id=session_id,
        agent_id="agent-1",
        messages=msgs,
    )
    session = AgentSession(session_id=session_id, runs=[run])
    if created_at:
        session.created_at = created_at
    return session


def _make_multi_run_session(
    session_id: str, runs_data: list[list[tuple[str, str]]], created_at: Optional[datetime] = None
) -> AgentSession:
    """Helper to build an AgentSession with multiple runs, each with message pairs."""
    runs = []
    for i, messages in enumerate(runs_data):
        msgs = []
        for user_text, assistant_text in messages:
            msgs.append(Message(role="user", content=user_text))
            msgs.append(Message(role="assistant", content=assistant_text))
        runs.append(
            RunOutput(
                run_id=f"run-{i + 1}",
                session_id=session_id,
                agent_id="agent-1",
                messages=msgs,
            )
        )
    session = AgentSession(session_id=session_id, runs=runs)
    if created_at:
        session.created_at = created_at
    return session


class _MockDbWithSessions:
    def __init__(self, sessions: list[AgentSession]):
        self._sessions = sessions

    def get_sessions(
        self,
        session_type: SessionType,
        limit: Optional[int] = None,
        user_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> list[Any]:
        result = list(self._sessions)
        if limit:
            result = result[:limit]
        return result

    def get_session(
        self,
        session_id: str = "",
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Any]:
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        return None


# --- search_past_sessions tests ---


@pytest.mark.parametrize("db", [None, _EmptySessionsDb()])
def test_search_past_sessions_returns_empty_json_when_no_sessions(db):
    agent = Agent(name="test-agent", db=db)
    search = _default_tools.get_search_past_sessions_function(agent)
    result = search()
    assert json.loads(result) == []


def test_search_past_sessions_returns_all_sessions():
    sessions = [
        _make_session("s1", [("Hello", "Hi there")]),
        _make_session("s2", [("Weather?", "It is sunny")]),
    ]
    db = _MockDbWithSessions(sessions)
    agent = Agent(name="test-agent", db=db)
    search = _default_tools.get_search_past_sessions_function(agent)
    result = json.loads(search())
    assert len(result) == 2
    assert result[0]["session_id"] == "s1"
    assert result[1]["session_id"] == "s2"
    # Preview should have runs list with user/assistant pairs
    assert len(result[0]["runs"]) == 1
    assert result[0]["runs"][0]["user"] == "Hello"
    assert result[0]["runs"][0]["assistant"] == "Hi there"


def test_search_past_sessions_excludes_current_session():
    sessions = [
        _make_session("current-session", [("Hello", "Hi")]),
        _make_session("other-session", [("Bye", "Goodbye")]),
    ]
    db = _MockDbWithSessions(sessions)
    agent = Agent(name="test-agent", db=db)
    search = _default_tools.get_search_past_sessions_function(agent, current_session_id="current-session")
    result = json.loads(search())
    assert len(result) == 1
    assert result[0]["session_id"] == "other-session"


def test_search_past_sessions_limits_runs_per_session():
    """num_past_session_runs_in_search caps the number of runs shown in preview."""
    session = _make_multi_run_session(
        "s1",
        [
            [("Run 1 Q", "Run 1 A")],
            [("Run 2 Q", "Run 2 A")],
            [("Run 3 Q", "Run 3 A")],
            [("Run 4 Q", "Run 4 A")],
            [("Run 5 Q", "Run 5 A")],
        ],
    )
    db = _MockDbWithSessions([session])
    agent = Agent(name="test-agent", db=db)

    # Default num_past_session_runs_in_search=3
    search = _default_tools.get_search_past_sessions_function(agent)
    result = json.loads(search())
    assert len(result[0]["runs"]) == 3
    assert result[0]["runs"][0]["user"] == "Run 1 Q"
    assert result[0]["runs"][2]["user"] == "Run 3 Q"

    # Custom limit of 1
    search = _default_tools.get_search_past_sessions_function(agent, num_past_session_runs_in_search=1)
    result = json.loads(search())
    assert len(result[0]["runs"]) == 1
    assert result[0]["runs"][0]["user"] == "Run 1 Q"


def test_search_past_sessions_preview_truncates_long_messages():
    """Messages longer than 200 chars are truncated with '...'."""
    long_msg = "x" * 300
    session = _make_session("s1", [(long_msg, "short reply")])
    db = _MockDbWithSessions([session])
    agent = Agent(name="test-agent", db=db)
    search = _default_tools.get_search_past_sessions_function(agent)
    result = json.loads(search())
    user_preview = result[0]["runs"][0]["user"]
    assert len(user_preview) == 203  # 200 + "..."
    assert user_preview.endswith("...")


# --- read_past_session tests ---


def test_read_past_session_returns_formatted_conversation():
    sessions = [
        _make_session("s1", [("Hello", "Hi there"), ("How are you?", "I am fine")]),
    ]
    db = _MockDbWithSessions(sessions)
    agent = Agent(name="test-agent", db=db)
    read = _default_tools.get_read_past_session_function(agent)
    result = read(session_id="s1")
    assert "User: Hello" in result
    assert "Assistant: Hi there" in result
    assert "User: How are you?" in result
    assert "Assistant: I am fine" in result
    assert "Session: s1" in result


def test_read_past_session_num_runs_limits_output():
    """num_runs parameter limits how many runs are included in the output."""
    session = _make_multi_run_session(
        "s1",
        [
            [("Run 1 Q", "Run 1 A")],
            [("Run 2 Q", "Run 2 A")],
            [("Run 3 Q", "Run 3 A")],
        ],
    )
    db = _MockDbWithSessions([session])
    agent = Agent(name="test-agent", db=db)
    read = _default_tools.get_read_past_session_function(agent)

    # Default: all runs
    result = read(session_id="s1")
    assert "Run 1 Q" in result
    assert "Run 3 A" in result

    # Limit to 2 runs
    result = read(session_id="s1", num_runs=2)
    assert "Run 1 Q" in result
    assert "Run 2 A" in result
    assert "Run 3 Q" not in result

    # Limit to 1 run
    result = read(session_id="s1", num_runs=1)
    assert "Run 1 Q" in result
    assert "Run 2 Q" not in result


def test_read_past_session_not_found():
    db = _EmptySessionsDb()
    agent = Agent(name="test-agent", db=db)
    read = _default_tools.get_read_past_session_function(agent)
    result = read(session_id="nonexistent")
    assert result == "Session not found."


def test_read_past_session_no_db():
    agent = Agent(name="test-agent", db=None)
    read = _default_tools.get_read_past_session_function(agent)
    result = read(session_id="s1")
    assert result == "No database configured."


# --- async tests ---


@pytest.mark.asyncio
@pytest.mark.parametrize("db", [None, _EmptySessionsDb()])
async def test_aget_search_past_sessions_returns_empty_json_when_no_sessions(db):
    agent = Agent(name="test-agent", db=db)
    search_fn = await _default_tools.aget_search_past_sessions_function(agent)
    result = await search_fn.entrypoint()  # type: ignore[misc]
    assert json.loads(result) == []


@pytest.mark.asyncio
async def test_aget_read_past_session_not_found():
    db = _EmptySessionsDb()
    agent = Agent(name="test-agent", db=db)
    read_fn = await _default_tools.aget_read_past_session_function(agent)
    result = await read_fn.entrypoint(session_id="nonexistent")  # type: ignore[misc]
    assert result == "Session not found."


# --- helper function tests ---


def test_get_message_text_str():
    msg = Message(role="user", content="hello")
    assert _default_tools._get_message_text(msg) == "hello"


def test_get_message_text_list():
    msg = Message(role="user", content=["hello", "world"])
    assert _default_tools._get_message_text(msg) == "hello world"


def test_get_message_text_none():
    msg = Message(role="user", content=None)
    assert _default_tools._get_message_text(msg) is None


def test_get_message_text_dict_blocks():
    """Dict content blocks with 'text' key (multi-modal providers) are extracted."""
    msg = Message(role="user", content=[{"type": "text", "text": "hello"}, {"type": "image_url", "url": "..."}])
    assert _default_tools._get_message_text(msg) == "hello"


def test_get_message_text_mixed_str_and_dict():
    """Mixed string and dict content blocks are both extracted."""
    msg = Message(role="user", content=["prefix", {"type": "text", "text": "suffix"}])
    assert _default_tools._get_message_text(msg) == "prefix suffix"


def test_extract_session_preview_returns_runs_format():
    """_extract_session_preview returns runs list instead of single preview string."""
    session = _make_session("s1", [("Hello", "Hi there")])
    preview = _default_tools._extract_session_preview(session)
    assert preview["session_id"] == "s1"
    assert "runs" in preview
    assert len(preview["runs"]) == 1
    assert preview["runs"][0]["user"] == "Hello"
    assert preview["runs"][0]["assistant"] == "Hi there"


def test_truncate():
    assert _default_tools._truncate("short") == "short"
    assert _default_tools._truncate("x" * 300) == "x" * 200 + "..."
    assert _default_tools._truncate("x" * 200) == "x" * 200


# --- existing tests (kept) ---


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
