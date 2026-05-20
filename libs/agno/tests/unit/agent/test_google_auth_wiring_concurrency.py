"""Tests for Google OAuth wiring and concurrency isolation.

Verifies that _wire_google_auth correctly wires Google toolkits to shared
GoogleAuthConfig, and that concurrent/multi-user scenarios maintain isolation.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agno.agent import _tools
from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunContext

try:
    from agno.tools.google.auth import GoogleAuthConfig
    from agno.tools.google.gmail import GmailTools
    from agno.tools.google.oauth_tools import GoogleOAuthTools

    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

pytestmark = pytest.mark.skipif(not HAS_GOOGLE, reason="Google dependencies not installed")


class TestWireGoogleAuthBasic:
    """Test basic _wire_google_auth functionality."""

    def test_wire_creates_shared_auth_config(self):
        """Multiple Google toolkits get the same shared auth_config."""
        gmail = GmailTools()
        oauth = GoogleOAuthTools()
        assert gmail.auth_config is None
        assert oauth.auth_config is None

        _tools._wire_google_auth([oauth, gmail])

        assert gmail.auth_config is not None
        assert oauth.auth_config is not None
        assert gmail.auth_config is oauth.auth_config

    def test_wire_registers_scopes(self):
        """Wiring registers the toolkit's scopes with the shared config."""
        gmail = GmailTools()
        _tools._wire_google_auth([gmail])

        assert gmail.auth_config is not None
        assert "gmail" in gmail.auth_config._services
        assert len(gmail.auth_config._services["gmail"]) > 0

    def test_wire_with_existing_config_uses_it(self):
        """Toolkits with pre-existing auth_config keep their config."""
        custom_config = GoogleAuthConfig()
        gmail = GmailTools(auth_config=custom_config)

        _tools._wire_google_auth([gmail])

        assert gmail.auth_config is custom_config

    def test_wire_returns_tools_unchanged_when_no_google_tools(self):
        """Non-Google tools pass through unchanged."""
        mock_tool = MagicMock()
        result = _tools._wire_google_auth([mock_tool])
        assert result == [mock_tool]

    def test_wire_returns_none_when_tools_is_none(self):
        """None input returns None."""
        result = _tools._wire_google_auth(None)
        assert result is None


class TestWireGoogleAuthIdempotency:
    """Test that wiring is idempotent."""

    def test_wire_is_idempotent_same_config(self):
        """Repeated wiring doesn't change the config."""
        gmail = GmailTools()
        oauth = GoogleOAuthTools()

        _tools._wire_google_auth([oauth, gmail])
        first_config = gmail.auth_config
        first_config_id = gmail._wired_config_id

        _tools._wire_google_auth([oauth, gmail])

        assert gmail.auth_config is first_config
        assert gmail._wired_config_id == first_config_id

    def test_wire_tracks_config_id_per_tool(self):
        """Each tool tracks its wired config via _wired_config_id."""
        gmail = GmailTools()
        oauth = GoogleOAuthTools()

        _tools._wire_google_auth([oauth, gmail])

        assert hasattr(gmail, "_wired_config_id")
        assert hasattr(oauth, "_wired_config_id")
        assert gmail._wired_config_id == oauth._wired_config_id


class TestWireGoogleAuthWithAgent:
    """Test wiring propagation from agent context."""

    def test_wire_propagates_store_token_in_db_from_agent_db(self):
        """When agent.db.store_auth_tokens=True, toolkits get store_token_in_db=True."""
        mock_db = MagicMock()
        mock_db.store_auth_tokens = True

        mock_agent = MagicMock()
        mock_agent.db = mock_db

        gmail = GmailTools()
        assert not getattr(gmail, "store_token_in_db", False)

        _tools._wire_google_auth([gmail], agent=mock_agent)

        assert gmail.store_token_in_db is True

    def test_wire_propagates_service_account_from_auth_config(self):
        """Service account config propagates from auth_config to toolkit."""
        config = GoogleAuthConfig(
            service_account_path="/path/to/key.json",
            delegated_user="admin@company.com",
        )
        gmail = GmailTools(auth_config=config)

        _tools._wire_google_auth([gmail])

        assert gmail.service_account_path == "/path/to/key.json"
        assert gmail.delegated_user == "admin@company.com"


class TestAgentGetToolsWiring:
    """Test wiring integration with Agent.get_tools()."""

    def test_get_tools_calls_wire_every_time(self):
        """_wire_google_auth is called on every get_tools() call."""
        agent = Agent(model="openai:gpt-5.4", tools=[GmailTools()])
        run_context = RunContext(run_id="test", session_id="test")
        run_response = RunOutput(run_id="test")
        session = MagicMock()

        call_count = 0
        original_wire = _tools._wire_google_auth

        def counting_wire(tools, agent=None):
            nonlocal call_count
            call_count += 1
            return original_wire(tools, agent)

        with patch.object(_tools, "_wire_google_auth", side_effect=counting_wire):
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)
            agent.get_tools(run_response=run_response, run_context=run_context, session=session)

        assert call_count == 3

    def test_get_tools_wires_gmail_tools(self):
        """get_tools() wires GmailTools with auth_config."""
        agent = Agent(model="openai:gpt-5.4", tools=[GoogleOAuthTools(), GmailTools()])
        run_context = RunContext(run_id="test", session_id="test")
        run_response = RunOutput(run_id="test")
        session = MagicMock()

        agent.get_tools(run_response=run_response, run_context=run_context, session=session)

        gmail = next((t for t in agent.tools if isinstance(t, GmailTools)), None)
        assert gmail is not None
        assert gmail.auth_config is not None


class TestDeepCopyIsolation:
    """Test that deep_copy creates isolated tool instances."""

    def test_deep_copy_creates_independent_tools(self):
        """deep_copy creates new tool list instances."""
        template = Agent(model="openai:gpt-5.4", tools=[GmailTools()])

        copy_a = template.deep_copy()
        copy_b = template.deep_copy()

        assert id(template.tools) != id(copy_a.tools)
        assert id(copy_a.tools) != id(copy_b.tools)

    @pytest.mark.asyncio
    async def test_concurrent_deep_copy_requests_isolated(self):
        """Concurrent requests via deep_copy get independently wired tools."""
        template = Agent(model="openai:gpt-5.4", tools=[GoogleOAuthTools(), GmailTools()])

        results = {}

        async def simulate_request(user_id: str):
            agent = template.deep_copy()
            run_context = RunContext(run_id=f"run-{user_id}", session_id=f"s-{user_id}", user_id=user_id)
            run_response = RunOutput(run_id=f"run-{user_id}")

            await agent.aget_tools(
                run_response=run_response, run_context=run_context, session=MagicMock(), user_id=user_id
            )

            gmail = next((t for t in agent.tools if isinstance(t, GmailTools)), None)
            results[user_id] = gmail.auth_config is not None if gmail else False

        await asyncio.gather(
            simulate_request("alice"),
            simulate_request("bob"),
            simulate_request("charlie"),
        )

        for user_id, is_wired in results.items():
            assert is_wired, f"{user_id}'s GmailTools not wired"


class TestCallableFactoryWiring:
    """Test wiring with callable tool factories."""

    @pytest.mark.asyncio
    async def test_callable_factory_tools_get_wired(self):
        """Tools from callable factories get wired per-user."""
        user_tools = {}

        def get_tools(run_context: RunContext):
            tools = [GoogleOAuthTools(), GmailTools()]
            user_tools[run_context.user_id] = tools
            return tools

        agent = Agent(model="openai:gpt-5.4", tools=get_tools)

        for user_id in ["alice", "bob", "charlie"]:
            run_context = RunContext(run_id=f"run-{user_id}", session_id=f"s-{user_id}", user_id=user_id)
            run_response = RunOutput(run_id=f"run-{user_id}")

            await agent.aget_tools(
                run_response=run_response, run_context=run_context, session=MagicMock(), user_id=user_id
            )

        for user_id, tools in user_tools.items():
            gmail = next((t for t in tools if isinstance(t, GmailTools)), None)
            assert gmail.auth_config is not None, f"{user_id}'s GmailTools not wired"
