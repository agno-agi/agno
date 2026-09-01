"""Regression tests: call-site ``dependencies`` merge with ``Agent.dependencies``.

Bug: call-site dependencies (e.g. channel/thread ids injected by the Slack/WhatsApp
interfaces) used to REPLACE ``Agent.dependencies`` wholesale, so prompt-template
variables configured on the agent silently dropped out of the system/user messages on
those surfaces. They must merge instead, with call-site keys winning on conflict.

These tests run the full ``run()`` / ``arun()`` path against a mock model (no network)
and assert the rendered system message — the same message an interface would send.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _system_content(response) -> str:
    """The system message is the first message sent to the model."""
    return response.messages[0].content


# ---------------------------------------------------------------------------
# Sync: run()
# ---------------------------------------------------------------------------


class TestRunDependenciesMerge:
    def test_agent_template_var_survives_callsite_runtime_keys(self):
        """The core bug: an interface passes runtime context deps; agent template vars must remain."""
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        # Simulate what Slack/WhatsApp do: pass call-site deps that do NOT include the agent's key.
        response = agent.run("hi", dependencies={"channel": "C123"})
        assert "X=RESOLVED" in _system_content(response)

    def test_callsite_key_also_available_for_substitution(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x} Z={z}",
        )
        response = agent.run("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)

    def test_callsite_key_overrides_agent_key_on_conflict(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "agent"},
            instructions="X={x}",
        )
        response = agent.run("hi", dependencies={"x": "call"})
        assert "X=call" in _system_content(response)

    def test_no_callsite_deps_agent_deps_still_resolve(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        response = agent.run("hi")
        assert "X=RESOLVED" in _system_content(response)

    def test_resolver_callable_merges_with_callsite(self):
        def resolve_x():
            return "RESOLVED"

        agent = Agent(
            model=MockModel(),
            dependencies={"x": resolve_x},
            instructions="X={x} Z={z}",
        )
        response = agent.run("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)


# ---------------------------------------------------------------------------
# Async: arun()
# ---------------------------------------------------------------------------


class TestArunDependenciesMerge:
    @pytest.mark.asyncio
    async def test_agent_template_var_survives_callsite_runtime_keys(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        response = await agent.arun("hi", dependencies={"channel": "C123"})
        assert "X=RESOLVED" in _system_content(response)

    @pytest.mark.asyncio
    async def test_callsite_key_also_available_for_substitution(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x} Z={z}",
        )
        response = await agent.arun("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)

    @pytest.mark.asyncio
    async def test_callsite_key_overrides_agent_key_on_conflict(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "agent"},
            instructions="X={x}",
        )
        response = await agent.arun("hi", dependencies={"x": "call"})
        assert "X=call" in _system_content(response)

    @pytest.mark.asyncio
    async def test_no_callsite_deps_agent_deps_still_resolve(self):
        agent = Agent(
            model=MockModel(),
            dependencies={"x": "RESOLVED"},
            instructions="X={x}",
        )
        response = await agent.arun("hi")
        assert "X=RESOLVED" in _system_content(response)

    @pytest.mark.asyncio
    async def test_async_resolver_callable_merges_with_callsite(self):
        async def resolve_x():
            return "RESOLVED"

        agent = Agent(
            model=MockModel(),
            dependencies={"x": resolve_x},
            instructions="X={x} Z={z}",
        )
        response = await agent.arun("hi", dependencies={"z": "1"})
        assert "X=RESOLVED Z=1" in _system_content(response)
