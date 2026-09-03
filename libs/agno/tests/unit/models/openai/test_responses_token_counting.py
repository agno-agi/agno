"""
Test token counting for OpenAI Responses API.

Reproduces the bug where count_tokens() returns incorrect counts when messages
contain provider_data with response_id (from previous API calls).
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


class TestResponsesTokenCounting:
    """Test count_tokens accuracy with response_id in provider_data."""

    def _create_conversation_with_response_id(self) -> list[Message]:
        """Create a realistic multi-turn conversation where assistant messages have response_id."""
        return [
            Message(role="user", content="Hello, can you help me with Python?"),
            Message(
                role="assistant",
                content="Of course! I'd be happy to help you with Python. What would you like to know?",
                # This simulates what happens after an API call - OpenAI returns a response_id
                provider_data={"response_id": "resp_abc123"},
            ),
            Message(role="user", content="How do I read a file in Python?"),
            Message(
                role="assistant",
                content="You can use the built-in open() function. Here's an example:\n\nwith open('file.txt', 'r') as f:\n    content = f.read()",
                provider_data={"response_id": "resp_def456"},
            ),
            Message(role="user", content="What about writing to a file?"),
        ]

    def _create_conversation_without_response_id(self) -> list[Message]:
        """Same conversation but without response_id in provider_data."""
        return [
            Message(role="user", content="Hello, can you help me with Python?"),
            Message(
                role="assistant",
                content="Of course! I'd be happy to help you with Python. What would you like to know?",
            ),
            Message(role="user", content="How do I read a file in Python?"),
            Message(
                role="assistant",
                content="You can use the built-in open() function. Here's an example:\n\nwith open('file.txt', 'r') as f:\n    content = f.read()",
            ),
            Message(role="user", content="What about writing to a file?"),
        ]

    def test_token_count_with_response_id_matches_without(self):
        """
        Token count should be the same regardless of whether messages have response_id.

        The bug: when messages have response_id in provider_data, _format_messages()
        truncates to only messages after the last assistant response, causing
        count_tokens() to return a much lower count.
        """
        model = OpenAIResponses(id="o3")

        msgs_with_id = self._create_conversation_with_response_id()
        msgs_without_id = self._create_conversation_without_response_id()

        # Mock the API call to return a consistent token count
        mock_response = MagicMock()
        mock_response.input_tokens = 100

        with patch.object(model, "get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.responses.input_tokens.count.return_value = mock_response
            mock_get_client.return_value = mock_client

            # Count tokens for both versions
            count_with_id = model.count_tokens(msgs_with_id)
            count_without_id = model.count_tokens(msgs_without_id)

            # Get the actual input passed to the API
            calls = mock_client.responses.input_tokens.count.call_args_list
            input_with_id = calls[0].kwargs["input"]
            input_without_id = calls[1].kwargs["input"]

            # The bug: with response_id, fewer messages are sent to the API
            # This test documents the bug - both should have the same number of messages
            assert len(input_with_id) == len(input_without_id), (
                f"Bug: messages with response_id sent {len(input_with_id)} items, "
                f"but without response_id sent {len(input_without_id)} items. "
                "Token counting should not be affected by response_id in provider_data."
            )

    def test_token_count_includes_all_messages(self):
        """count_tokens should include ALL messages, not just those after the last response_id."""
        model = OpenAIResponses(id="o3")

        msgs = self._create_conversation_with_response_id()
        # 5 messages total: user, assistant, user, assistant, user

        mock_response = MagicMock()
        mock_response.input_tokens = 100

        with patch.object(model, "get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.responses.input_tokens.count.return_value = mock_response
            mock_get_client.return_value = mock_client

            model.count_tokens(msgs)

            call_kwargs = mock_client.responses.input_tokens.count.call_args.kwargs
            formatted_input = call_kwargs["input"]

            # Should have all 5 messages (3 user + 2 assistant)
            # The bug: only 1 message (the last user message) is sent
            assert len(formatted_input) >= 5, (
                f"Expected at least 5 formatted messages, got {len(formatted_input)}. "
                "Token counting is truncating messages incorrectly."
            )

    def test_non_reasoning_model_not_affected(self):
        """Non-reasoning models should not have this issue since truncation only happens for reasoning models."""
        model = OpenAIResponses(id="gpt-4o")  # Not a reasoning model

        msgs = self._create_conversation_with_response_id()

        mock_response = MagicMock()
        mock_response.input_tokens = 100

        with patch.object(model, "get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.responses.input_tokens.count.return_value = mock_response
            mock_get_client.return_value = mock_client

            model.count_tokens(msgs)

            call_kwargs = mock_client.responses.input_tokens.count.call_args.kwargs
            formatted_input = call_kwargs["input"]

            # Non-reasoning models don't truncate
            assert len(formatted_input) >= 5

    @pytest.mark.asyncio
    async def test_acount_tokens_includes_all_messages(self):
        """Async version should also count ALL messages."""
        model = OpenAIResponses(id="o3")

        msgs = self._create_conversation_with_response_id()

        mock_response = MagicMock()
        mock_response.input_tokens = 100

        with patch.object(model, "get_async_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.responses.input_tokens.count = MagicMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            await model.acount_tokens(msgs)

            call_kwargs = mock_client.responses.input_tokens.count.call_args.kwargs
            formatted_input = call_kwargs["input"]

            # Should have all 5 messages
            assert len(formatted_input) >= 5, (
                f"Expected at least 5 formatted messages, got {len(formatted_input)}. "
                "Async token counting is truncating messages incorrectly."
            )
