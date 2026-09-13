"""Tests for per-request tool filtering via run(tools=...) / arun(tools=...).

Verifies that passing tools= to run/arun populates RunContext.tools,
which get_resolved_tools() returns in preference to agent.tools.
This enables concurrent-safe per-request tool selection without mutating
shared agent state.

See: https://github.com/agno-agi/agno/issues/7168
"""

import asyncio
from unittest.mock import MagicMock, patch

from agno.agent.agent import Agent
from agno.run import RunContext
from agno.tools.toolkit import Toolkit
from agno.utils.callables import get_resolved_tools


class FakeToolA(Toolkit):
    def __init__(self):
        super().__init__(name="tool_a")
        self.register(self.do_a)

    def do_a(self) -> str:
        """Tool A."""
        return "a"


class FakeToolB(Toolkit):
    def __init__(self):
        super().__init__(name="tool_b")
        self.register(self.do_b)

    def do_b(self) -> str:
        """Tool B."""
        return "b"


class FakeToolC(Toolkit):
    def __init__(self):
        super().__init__(name="tool_c")
        self.register(self.do_c)

    def do_c(self) -> str:
        """Tool C."""
        return "c"


# ---------------------------------------------------------------------------
# get_resolved_tools respects RunContext.tools
# ---------------------------------------------------------------------------


class TestGetResolvedToolsRunContext:
    def test_returns_agent_tools_when_no_run_context(self):
        agent = MagicMock()
        agent.tools = [FakeToolA(), FakeToolB()]
        result = get_resolved_tools(agent, run_context=None)
        assert result == agent.tools

    def test_returns_run_context_tools_when_set(self):
        agent = MagicMock()
        agent.tools = [FakeToolA(), FakeToolB(), FakeToolC()]
        subset = [FakeToolA()]
        ctx = RunContext(run_id="test", session_id="s1", tools=subset)
        result = get_resolved_tools(agent, run_context=ctx)
        assert result == subset
        assert len(result) == 1

    def test_returns_agent_tools_when_run_context_tools_is_none(self):
        agent = MagicMock()
        agent.tools = [FakeToolA()]
        ctx = RunContext(run_id="test", session_id="s1", tools=None)
        result = get_resolved_tools(agent, run_context=ctx)
        assert result == agent.tools


# ---------------------------------------------------------------------------
# Agent.run() and Agent.arun() accept tools parameter
# ---------------------------------------------------------------------------


class TestRunToolsParameter:
    def test_run_accepts_tools_kwarg(self):
        """Verify the tools parameter exists on Agent.run() signature."""
        import inspect

        sig = inspect.signature(Agent.run)
        assert "tools" in sig.parameters
        param = sig.parameters["tools"]
        assert param.default is None

    def test_arun_accepts_tools_kwarg(self):
        """Verify the tools parameter exists on Agent.arun() signature."""
        import inspect

        sig = inspect.signature(Agent.arun)
        assert "tools" in sig.parameters
        param = sig.parameters["tools"]
        assert param.default is None
