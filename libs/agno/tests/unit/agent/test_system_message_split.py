"""Tests for cache_system_prompt_blocks (split system message into static + dynamic)."""

from unittest.mock import MagicMock

import pytest

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.session import AgentSession


def _session():
    return AgentSession(session_id="test-session")


def _make_mock_model():
    """Create a minimal mock that satisfies get_system_message's requirements."""
    model = MagicMock()
    model.get_instructions_for_model.return_value = None
    model.get_system_message_for_model.return_value = None
    model.supports_native_structured_outputs = False
    model.supports_json_schema_outputs = False
    return model


def _make_agent(**kwargs) -> Agent:
    agent = Agent(**kwargs)
    if agent.model is None:
        agent.model = _make_mock_model()
    return agent


class TestCacheSystemPromptBlocks:
    """Tests for Agent.cache_system_prompt_blocks splitting behaviour."""

    def test_disabled_returns_single_message(self):
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            add_datetime_to_context=True,
            cache_system_prompt_blocks=False,
        )
        result = agent.get_system_message(session=_session())
        assert isinstance(result, Message)

    def test_enabled_returns_list(self):
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        assert isinstance(result, list)
        assert len(result) == 2

    def test_static_block_has_cache_control(self):
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_msg = result[0]
        assert static_msg.provider_data is not None
        assert static_msg.provider_data["cache_control"] == {"type": "ephemeral"}

    def test_dynamic_block_has_no_cache_control(self):
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        dynamic_msg = result[1]
        assert dynamic_msg.provider_data is None

    def test_static_block_contains_description_and_instructions(self):
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_content = result[0].content
        assert "A helpful assistant" in static_content
        assert "Be concise" in static_content

    def test_dynamic_block_contains_datetime(self):
        agent = _make_agent(
            description="A helpful assistant",
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        dynamic_content = result[1].content
        assert "current time" in dynamic_content.lower()

    def test_static_block_does_not_contain_datetime(self):
        agent = _make_agent(
            description="A helpful assistant",
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_content = result[0].content
        assert "current time" not in static_content.lower()

    def test_markdown_in_static_block(self):
        """markdown instruction is static -- should be in static block, not dynamic."""
        agent = _make_agent(
            description="A helpful assistant",
            markdown=True,
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_content = result[0].content
        assert "markdown" in static_content.lower()

    def test_agent_name_in_static_block(self):
        agent = _make_agent(
            description="A helpful assistant",
            name="TestBot",
            add_name_to_context=True,
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_content = result[0].content
        assert "TestBot" in static_content

    def test_only_static_content_returns_single_item_list(self):
        """When there's no dynamic content, return list with just the static block."""
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].provider_data is not None
        assert result[0].provider_data["cache_control"] == {"type": "ephemeral"}

    def test_custom_system_message_ignores_flag(self):
        """When agent.system_message is set, cache_system_prompt_blocks has no effect."""
        agent = _make_agent(
            system_message="Custom system message",
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        assert isinstance(result, Message)
        assert result.content == "Custom system message"

    def test_build_context_false_returns_none(self):
        agent = _make_agent(
            build_context=False,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        assert result is None

    def test_role_in_static_block(self):
        agent = _make_agent(
            role="You are a data analyst",
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_content = result[0].content
        assert "data analyst" in static_content

    def test_expected_output_in_static_block(self):
        agent = _make_agent(
            description="Helper",
            expected_output="A JSON object",
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        static_content = result[0].content
        assert "A JSON object" in static_content

    def test_all_messages_have_correct_role(self):
        agent = _make_agent(
            description="A helpful assistant",
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = agent.get_system_message(session=_session())
        for msg in result:
            assert msg.role == "system"


class TestCacheSystemPromptBlocksAsync:
    """Async variant tests for cache_system_prompt_blocks."""

    @pytest.mark.asyncio
    async def test_async_enabled_returns_list(self):
        agent = _make_agent(
            description="A helpful assistant",
            instructions=["Be concise"],
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = await agent.aget_system_message(session=_session())
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_async_static_has_cache_control(self):
        agent = _make_agent(
            description="A helpful assistant",
            add_datetime_to_context=True,
            cache_system_prompt_blocks=True,
        )
        result = await agent.aget_system_message(session=_session())
        assert result[0].provider_data["cache_control"] == {"type": "ephemeral"}
        assert result[1].provider_data is None

    @pytest.mark.asyncio
    async def test_async_disabled_returns_single_message(self):
        agent = _make_agent(
            description="A helpful assistant",
            cache_system_prompt_blocks=False,
        )
        result = await agent.aget_system_message(session=_session())
        assert isinstance(result, Message)
