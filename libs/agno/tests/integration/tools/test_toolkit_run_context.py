"""Integration tests for @tool-decorated Toolkit methods with framework-injected parameters.

A Toolkit method decorated with @tool (e.g. to set a custom tool name) that declares a
run_context parameter failed at call time with a pydantic "Missing required argument" error,
because the bound wrapper created during registration hid the original signature
from FunctionCall._build_entrypoint_args.
"""

import uuid
from typing import Optional

import pytest

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools import Toolkit, tool


class WatchlistTools(Toolkit):
    """Toolkit whose methods need a custom tool name (hence @tool) and run_context."""

    def __init__(self, **kwargs):
        self.captured_session_id: Optional[str] = None
        self.called_variant: Optional[str] = None
        super().__init__(
            name="watchlist_tools",
            tools=[self.add_to_watchlist, self.aadd_to_watchlist],
            **kwargs,
        )

    @tool(name="add_watch_task")
    def add_to_watchlist(self, symbol: str, run_context: RunContext) -> str:
        """Add a stock symbol to the watchlist.

        Args:
            symbol: The stock symbol to watch.
        """
        self.captured_session_id = run_context.session_id
        self.called_variant = "sync"
        if run_context.session_state is None:
            run_context.session_state = {}
        run_context.session_state.setdefault("watchlist", []).append(symbol)
        return f"Added {symbol} to the watchlist"

    # Async variant registered under the same tool name; preferred by agent.arun()
    @tool(name="add_watch_task")
    async def aadd_to_watchlist(self, symbol: str, run_context: RunContext) -> str:
        """Add a stock symbol to the watchlist.

        Args:
            symbol: The stock symbol to watch.
        """
        self.captured_session_id = run_context.session_id
        self.called_variant = "async"
        if run_context.session_state is None:
            run_context.session_state = {}
        run_context.session_state.setdefault("watchlist", []).append(symbol)
        return f"Added {symbol} to the watchlist"


def _build_agent(toolkit: WatchlistTools, db: InMemoryDb, session_id: str) -> Agent:
    return Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=db,
        session_id=session_id,
        tools=[toolkit],
        instructions="Use the add_watch_task tool to add stocks to the watchlist.",
        telemetry=False,
    )


def _get_tool_call_names(response) -> list:
    names = []
    for msg in response.messages or []:
        for tool_call in msg.tool_calls or []:
            names.append(tool_call.get("function", {}).get("name"))
    return names


def test_decorated_toolkit_tool_receives_run_context():
    session_id = f"watchlist_test_{uuid.uuid4()}"
    toolkit = WatchlistTools()
    db = InMemoryDb()
    agent = _build_agent(toolkit, db, session_id)

    response = agent.run("Add stock 601838 to my watchlist")

    # The custom-named tool was called and did not fail with a validation error
    assert "add_watch_task" in _get_tool_call_names(response)
    tool_messages = [msg for msg in response.messages or [] if msg.role == "tool"]
    assert tool_messages, "Expected a tool result message"
    assert all("Missing required argument" not in str(msg.content) for msg in tool_messages)

    # run_context was injected into the sync method
    assert toolkit.called_variant == "sync"
    assert toolkit.captured_session_id == session_id

    # Session state mutated through run_context was persisted
    session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    assert session is not None
    assert "601838" in session.session_data["session_state"]["watchlist"]


@pytest.mark.asyncio
async def test_decorated_toolkit_tool_receives_run_context_async():
    session_id = f"watchlist_test_{uuid.uuid4()}"
    toolkit = WatchlistTools()
    db = InMemoryDb()
    agent = _build_agent(toolkit, db, session_id)

    response = await agent.arun("Add stock 601838 to my watchlist")

    # The custom-named tool was called and did not fail with a validation error
    assert "add_watch_task" in _get_tool_call_names(response)
    tool_messages = [msg for msg in response.messages or [] if msg.role == "tool"]
    assert tool_messages, "Expected a tool result message"
    assert all("Missing required argument" not in str(msg.content) for msg in tool_messages)

    # run_context was injected into the async variant (preferred by arun)
    assert toolkit.called_variant == "async"
    assert toolkit.captured_session_id == session_id

    # Session state mutated through run_context was persisted
    session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    assert session is not None
    assert "601838" in session.session_data["session_state"]["watchlist"]
