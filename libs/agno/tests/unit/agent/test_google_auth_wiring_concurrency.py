"""Tests for per-tool _wired_config_id tracking in concurrent scenarios.

These tests verify the per-tool tracking mechanism works correctly
for various usage patterns, especially concurrent requests.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agno.agent import _tools
from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunContext

try:
    from agno.tools.google.gmail import GmailTools
    from agno.tools.google.oauth_tools import GoogleOAuthTools

    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

pytestmark = pytest.mark.skipif(not HAS_GOOGLE, reason="Google dependencies not installed")


class TestGoogleAuthWiringIdempotent:
    """Test that _wire_google_auth is idempotent and safe for all scenarios."""

    def test_wire_called_every_get_tools(self):
        """_wire_google_auth is called every get_tools() but is idempotent."""
        agent = Agent(model="openai:gpt-4o", tools=[GmailTools()])
        run_context = RunContext(run_id="test", session_id="test")
        run_response = RunOutput(run_id="test")
        session = MagicMock()

        call_count = 0
        original_wire = _tools._wire_google_auth

        def counting_wire(tools):
            nonlocal call_count
            call_count += 1
            return original_wire(tools)

        with patch.object(_tools, "_wire_google_auth", side_effect=counting_wire):
            # Call get_tools multiple times (simulates retries)
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)

        # Called every time, but idempotent - no duplicate wiring
        assert call_count == 3, f"Expected 3 calls, got {call_count}"

    def test_tools_wired_correctly_after_multiple_calls(self):
        """Tools should remain wired after multiple get_tools() calls."""
        agent = Agent(model="openai:gpt-4o", tools=[GoogleOAuthTools(), GmailTools()])
        run_context = RunContext(run_id="test", session_id="test")
        run_response = RunOutput(run_id="test")
        session = MagicMock()

        # Call multiple times
        for _ in range(3):
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)

        # Tools should be wired
        gmail = next((t for t in agent.tools if isinstance(t, GmailTools)), None)
        assert gmail.oauth_config is not None

    def test_per_tool_tracking_skips_already_wired(self):
        """Tools track their wired state via _wired_config_id."""
        gmail = GmailTools()
        oauth = GoogleOAuthTools()

        # First wire
        _tools._wire_google_auth([oauth, gmail])

        # Tools should have _wired_config_id set
        assert hasattr(gmail, "_wired_config_id")
        assert hasattr(oauth, "_wired_config_id")
        assert gmail._wired_config_id == oauth._wired_config_id

        # Both should share same config
        assert gmail.oauth_config is oauth.oauth_config

        # Second wire should be a no-op (same config)
        original_config = gmail.oauth_config
        _tools._wire_google_auth([oauth, gmail])

        # Config should be unchanged
        assert gmail.oauth_config is original_config


class TestAgentOSDeepCopyIsolation:
    """Test that deep_copy provides proper isolation (AgentOS pattern)."""

    def test_deep_copy_creates_independent_tools(self):
        """Each deep_copy should have its own tools list."""
        template = Agent(model="openai:gpt-4o", tools=[GmailTools()])

        copy_a = template.deep_copy()
        copy_b = template.deep_copy()

        assert id(template.tools) != id(copy_a.tools)
        assert id(copy_a.tools) != id(copy_b.tools)

    @pytest.mark.asyncio
    async def test_agentos_concurrent_requests_isolated(self):
        """Simulate AgentOS: concurrent requests with deep_copy are isolated."""
        template = Agent(model="openai:gpt-4o", tools=[GoogleOAuthTools(), GmailTools()])

        results = {}

        async def simulate_request(user_id: str, delay: float = 0):
            await asyncio.sleep(delay)
            # AgentOS does deep_copy per request
            agent = template.deep_copy()

            run_context = RunContext(run_id=f"run-{user_id}", session_id=f"s-{user_id}", user_id=user_id)
            run_response = RunOutput(run_id=f"run-{user_id}")

            tools = await agent.aget_tools(
                run_response=run_response, run_context=run_context, session=MagicMock(), user_id=user_id
            )

            # Check if tools are wired
            gmail = next((t for t in agent.tools if isinstance(t, GmailTools)), None)
            results[user_id] = {
                "tools_count": len(tools),
                "gmail_wired": gmail.oauth_config is not None if gmail else False,
            }

        await asyncio.gather(
            simulate_request("alice", 0),
            simulate_request("bob", 0.01),
            simulate_request("charlie", 0.02),
        )

        # All users should have wired tools
        for user_id, result in results.items():
            assert result["gmail_wired"], f"{user_id}'s GmailTools not wired"


class TestSharedAgentStaticTools:
    """Test shared agent with static tools (same tool objects)."""

    @pytest.mark.asyncio
    async def test_shared_agent_static_tools_all_wired(self):
        """Shared agent with static tools: all users see wired tools."""
        # Same agent instance shared across requests
        agent = Agent(model="openai:gpt-4o", tools=[GoogleOAuthTools(), GmailTools()])

        results = {}

        async def simulate_request(user_id: str, delay: float = 0):
            await asyncio.sleep(delay)
            run_context = RunContext(run_id=f"run-{user_id}", session_id=f"s-{user_id}", user_id=user_id)
            run_response = RunOutput(run_id=f"run-{user_id}")

            await agent.aget_tools(
                run_response=run_response, run_context=run_context, session=MagicMock(), user_id=user_id
            )

            gmail = next((t for t in agent.tools if isinstance(t, GmailTools)), None)
            results[user_id] = gmail.oauth_config is not None if gmail else False

        await asyncio.gather(
            simulate_request("alice", 0),
            simulate_request("bob", 0.01),
            simulate_request("charlie", 0.02),
        )

        # All users see the SAME tool objects, which are wired by first user
        for user_id, is_wired in results.items():
            assert is_wired, f"{user_id}'s GmailTools not wired"


class TestSharedAgentCallableFactory:
    """Test shared agent with callable factory (different tool objects per user)."""

    @pytest.mark.asyncio
    async def test_shared_agent_cached_factory_all_wired(self):
        """Shared agent with cached factory: ALL users get wired tools.

        Even with different user_ids (different cache keys), each user's
        tools are wired because _wire_google_auth is called every time
        and is idempotent.
        """
        user_tools = {}

        def get_tools(run_context: RunContext):
            tools = [GoogleOAuthTools(), GmailTools()]
            user_tools[run_context.user_id] = tools
            return tools

        # Shared agent with cached callable factory (default)
        agent = Agent(
            model="openai:gpt-4o",
            tools=get_tools,
            cache_callables=True,
        )

        # Sequential requests
        for user_id in ["alice", "bob", "charlie"]:
            run_context = RunContext(run_id=f"run-{user_id}", session_id=f"s-{user_id}", user_id=user_id)
            run_response = RunOutput(run_id=f"run-{user_id}")

            await agent.aget_tools(
                run_response=run_response, run_context=run_context, session=MagicMock(), user_id=user_id
            )

        # ALL users should have wired tools
        for user_id, tools in user_tools.items():
            gmail = next((t for t in tools if isinstance(t, GmailTools)), None)
            assert gmail.oauth_config is not None, f"{user_id}'s GmailTools not wired"

    @pytest.mark.asyncio
    async def test_shared_agent_uncached_factory_all_wired(self):
        """Shared agent with uncached factory: ALL users get wired tools.

        Even with fresh tool instances per call, each user's tools are
        wired because _wire_google_auth is called every time and is idempotent.
        """
        user_tools = {}

        def get_tools(run_context: RunContext):
            tools = [GoogleOAuthTools(), GmailTools()]
            user_tools[run_context.user_id] = tools
            return tools

        # Shared agent with UNCACHED callable factory
        agent = Agent(
            model="openai:gpt-4o",
            tools=get_tools,
            cache_callables=False,
        )

        # Sequential requests
        for user_id in ["alice", "bob", "charlie"]:
            run_context = RunContext(run_id=f"run-{user_id}", session_id=f"s-{user_id}", user_id=user_id)
            run_response = RunOutput(run_id=f"run-{user_id}")

            await agent.aget_tools(
                run_response=run_response, run_context=run_context, session=MagicMock(), user_id=user_id
            )

        # ALL users should have wired tools
        for user_id, tools in user_tools.items():
            gmail = next((t for t in tools if isinstance(t, GmailTools)), None)
            assert gmail.oauth_config is not None, f"{user_id}'s GmailTools not wired"


class TestWiringAcrossRuns:
    """Test wiring behavior across multiple runs."""

    @pytest.mark.asyncio
    async def test_wiring_works_across_runs(self):
        """Wiring should work correctly across multiple runs."""
        agent = Agent(model="openai:gpt-4o", tools=[GmailTools()])

        call_count = 0
        original_wire = _tools._wire_google_auth

        def counting_wire(tools):
            nonlocal call_count
            call_count += 1
            return original_wire(tools)

        with patch.object(_tools, "_wire_google_auth", side_effect=counting_wire):
            # Run 1
            run_context1 = RunContext(run_id="run-1", session_id="s-1")
            run_response1 = RunOutput(run_id="run-1")
            await agent.aget_tools(run_response=run_response1, run_context=run_context1, session=MagicMock())
            assert call_count == 1

            # Run 2
            run_context2 = RunContext(run_id="run-2", session_id="s-2")
            run_response2 = RunOutput(run_id="run-2")
            await agent.aget_tools(run_response=run_response2, run_context=run_context2, session=MagicMock())
            assert call_count == 2, "Wire called each run"

        # Tools should still be wired
        gmail = next((t for t in agent.tools if isinstance(t, GmailTools)), None)
        assert gmail.oauth_config is not None
