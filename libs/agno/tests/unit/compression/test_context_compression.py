"""Unit tests for context compression algorithm and message ID filtering.

These tests verify the correctness of:
1. Context compression using from_history flag to identify current user
2. Keeping only the last tool batch (compressing earlier batches)
3. Message ID tracking (only compressed messages are tracked)
4. History filtering (messages with IDs in CompressedContext.message_ids are filtered)
"""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.compression.context import CompressedContext
from agno.compression.manager import CompressionManager
from agno.models.message import Message


class TestContextCompressionSlicing:
    """Test that _compress_context correctly identifies which messages to compress."""

    def test_keeps_current_user_message(self):
        """Verify that the current user message (from_history=False) is kept, not compressed."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary of earlier conversation"
        manager.model.response = MagicMock(return_value=mock_response)

        messages = [
            Message(role="system", content="You are a helpful assistant", id="sys1"),
            Message(role="user", content="First question", id="user1", from_history=True),
            Message(role="assistant", content="First answer", id="asst1", from_history=True),
            Message(role="user", content="Second question", id="user2", from_history=True),
            Message(role="assistant", content="Second answer", id="asst2", from_history=True),
            Message(role="user", content="Current question", id="user3", from_history=False),  # Current
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages.copy())

        assert result is not None
        # History messages should be compressed
        assert "user1" in result.message_ids
        assert "asst1" in result.message_ids
        assert "user2" in result.message_ids
        assert "asst2" in result.message_ids
        # Current user (from_history=False) should NOT be compressed
        assert "user3" not in result.message_ids
        # System message should NOT be compressed
        assert "sys1" not in result.message_ids

    def test_keeps_last_tool_batch(self):
        """Verify that the last tool batch (after current user) is kept."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary"
        manager.model.response = MagicMock(return_value=mock_response)

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            Message(role="assistant", content="Old answer", id="asst1", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
            # Last tool batch (should be kept)
            Message(
                role="assistant",
                content="",
                id="asst2",
                tool_calls=[{"id": "tc1", "function": {"name": "search", "arguments": "{}"}}],
            ),
            Message(role="tool", content="Tool result", id="tool1", tool_call_id="tc1"),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages.copy())

        assert result is not None
        # History should be compressed
        assert "user1" in result.message_ids
        assert "asst1" in result.message_ids
        # Current user should NOT be compressed
        assert "user2" not in result.message_ids
        # Last tool batch should NOT be compressed
        assert "asst2" not in result.message_ids
        assert "tool1" not in result.message_ids

    def test_no_compression_with_too_few_messages(self):
        """Verify compression is skipped when there are fewer than 3 messages."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Question", id="user1"),
        ]

        result = manager._compress_context(messages.copy())
        assert result is None

    def test_no_compression_when_nothing_to_compress(self):
        """Verify no compression happens when only current turn exists."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary"
        manager.model.response = MagicMock(return_value=mock_response)

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="First and only question", id="user1", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages.copy())

        # Should return None since there's nothing to compress
        assert result is None

    def test_message_list_modified_correctly(self):
        """Verify that messages list is correctly modified after compression."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary of old conversation"
        manager.model.response = MagicMock(return_value=mock_response)

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            Message(role="assistant", content="Old answer", id="asst1", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            manager._compress_context(messages)

        # After compression:
        # - System message should remain at position 0
        # - Summary message should be inserted at position 1 (as user message)
        # - Current user message should be at position 2
        assert len(messages) == 3
        assert messages[0].role == "system"
        assert messages[1].role == "user"  # Summary (provides context to LLM)
        assert "<previous_summary>" in messages[1].content
        assert messages[2].role == "user"
        assert messages[2].content == "Current question"

    def test_merges_previous_compression_context(self):
        """Verify that message IDs are merged with previous compressed context."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "New summary"
        manager.model.response = MagicMock(return_value=mock_response)

        previous_context = CompressedContext(
            content="Old summary",
            message_ids={"old_user1", "old_asst1"},
        )

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Question", id="user1", from_history=True),
            Message(role="assistant", content="Answer", id="asst1", from_history=True),
            Message(role="user", content="Current", id="user2", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages.copy(), previous_context)

        assert result is not None
        # Should contain both old and new message IDs
        assert "old_user1" in result.message_ids
        assert "old_asst1" in result.message_ids
        assert "user1" in result.message_ids
        assert "asst1" in result.message_ids
        # But not the current turn
        assert "user2" not in result.message_ids

    def test_compresses_earlier_tool_batches(self):
        """Verify that earlier tool batches are compressed, only last batch is kept."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary of history and earlier tool batches"
        manager.model.response = MagicMock(return_value=mock_response)

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            Message(role="assistant", content="Old answer", id="asst1", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
            # First tool batch (should be compressed)
            Message(
                role="assistant",
                content="",
                id="asst2",
                tool_calls=[{"id": "tc1", "function": {"name": "search", "arguments": "{}"}}],
            ),
            Message(role="tool", content="Result 1", id="tool1", tool_call_id="tc1"),
            # Second tool batch (should be compressed)
            Message(
                role="assistant",
                content="",
                id="asst3",
                tool_calls=[{"id": "tc2", "function": {"name": "analyze", "arguments": "{}"}}],
            ),
            Message(role="tool", content="Result 2", id="tool2", tool_call_id="tc2"),
            # Third (last) tool batch (should be KEPT)
            Message(
                role="assistant",
                content="",
                id="asst4",
                tool_calls=[{"id": "tc3", "function": {"name": "summarize", "arguments": "{}"}}],
            ),
            Message(role="tool", content="Result 3", id="tool3", tool_call_id="tc3"),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages.copy())

        assert result is not None
        # History should be compressed
        assert "user1" in result.message_ids
        assert "asst1" in result.message_ids
        # Earlier tool batches should be compressed
        assert "asst2" in result.message_ids
        assert "tool1" in result.message_ids
        assert "asst3" in result.message_ids
        assert "tool2" in result.message_ids
        # Current user should NOT be compressed
        assert "user2" not in result.message_ids
        # Last tool batch should NOT be compressed
        assert "asst4" not in result.message_ids
        assert "tool3" not in result.message_ids

    def test_tool_batch_from_history_is_compressed(self):
        """Verify that tool batches from history are compressed, not kept."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary"
        manager.model.response = MagicMock(return_value=mock_response)

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            # Tool batch from history (should be compressed)
            Message(
                role="assistant",
                content="",
                id="asst1",
                tool_calls=[{"id": "tc1", "function": {"name": "old_tool", "arguments": "{}"}}],
                from_history=True,
            ),
            Message(role="tool", content="Old result", id="tool1", tool_call_id="tc1", from_history=True),
            Message(role="assistant", content="Old final answer", id="asst2", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages.copy())

        assert result is not None
        # All history including tool batch should be compressed
        assert "user1" in result.message_ids
        assert "asst1" in result.message_ids
        assert "tool1" in result.message_ids
        assert "asst2" in result.message_ids
        # Current user should NOT be compressed
        assert "user2" not in result.message_ids


class TestAsyncContextCompression:
    """Test the async version of context compression."""

    @pytest.mark.asyncio
    async def test_acompress_context_keeps_current_user(self):
        """Verify async compression keeps the current user message (from_history=False)."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Summary"
        # Use AsyncMock for async method
        manager.model.aresponse = AsyncMock(return_value=mock_response)

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            Message(role="assistant", content="Old answer", id="asst1", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = await manager._acompress_context(messages.copy())

        assert result is not None
        assert "user1" in result.message_ids
        assert "asst1" in result.message_ids
        assert "user2" not in result.message_ids


class TestCompressedContextFiltering:
    """Test that CompressedContext.message_ids are used to filter history."""

    def test_filter_history_by_message_ids(self):
        """Simulate how Agent/Team filters history using message_ids."""
        # This simulates the logic added to _get_run_messages
        compressed_ctx = CompressedContext(
            content="Summary",
            message_ids={"user1", "asst1", "user2", "asst2"},
        )

        history = [
            Message(role="user", content="Old Q1", id="user1"),
            Message(role="assistant", content="Old A1", id="asst1"),
            Message(role="user", content="Old Q2", id="user2"),
            Message(role="assistant", content="Old A2", id="asst2"),
            Message(role="user", content="Recent Q", id="user3"),
            Message(role="assistant", content="Recent A", id="asst3"),
        ]

        # Filter as done in _get_run_messages
        filtered_history = [msg for msg in history if msg.id not in compressed_ctx.message_ids]

        # Only messages not in compressed context should remain
        assert len(filtered_history) == 2
        assert filtered_history[0].id == "user3"
        assert filtered_history[1].id == "asst3"

    def test_filter_with_no_compression_context(self):
        """Verify filtering is skipped when there's no compressed context."""
        compressed_ctx: Optional[CompressedContext] = None

        history = [
            Message(role="user", content="Q1", id="user1"),
            Message(role="assistant", content="A1", id="asst1"),
        ]

        # Simulate the conditional check
        if compressed_ctx and compressed_ctx.message_ids:
            filtered_history = [msg for msg in history if msg.id not in compressed_ctx.message_ids]
        else:
            filtered_history = history

        # All messages should remain
        assert len(filtered_history) == 2

    def test_filter_with_empty_message_ids(self):
        """Verify filtering handles empty message_ids gracefully."""
        compressed_ctx = CompressedContext(
            content="Summary",
            message_ids=set(),  # Empty
        )

        history = [
            Message(role="user", content="Q1", id="user1"),
            Message(role="assistant", content="A1", id="asst1"),
        ]

        # Simulate the conditional check
        if compressed_ctx and compressed_ctx.message_ids:
            filtered_history = [msg for msg in history if msg.id not in compressed_ctx.message_ids]
        else:
            filtered_history = history

        # All messages should remain since message_ids is empty
        assert len(filtered_history) == 2


class TestIncrementalCompression:
    """Test that incremental compression includes previous summary."""

    def test_incremental_compression_includes_previous_summary(self):
        """Verify that when a previous compression context exists, its content is included in the LLM prompt."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        mock_response = MagicMock()
        mock_response.content = "Merged summary"
        manager.model.response = MagicMock(return_value=mock_response)

        previous_context = CompressedContext(
            content="TASK: Research topic\nDATA: fact1=value1",
            message_ids={"old_user1", "old_asst1"},
        )

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Question", id="user1", from_history=True),
            Message(role="assistant", content="Answer", id="asst1", from_history=True),
            Message(role="user", content="Current", id="user2", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            manager._compress_context(messages.copy(), previous_context)

        # Check that the model was called with the previous summary in the prompt
        call_args = manager.model.response.call_args
        user_message = call_args.kwargs["messages"][1]
        assert "Previous summary" in user_message.content
        assert "TASK: Research topic" in user_message.content
        assert "fact1=value1" in user_message.content
        assert "New conversation to incorporate" in user_message.content


class TestCompressionErrorHandling:
    """Test error handling and recovery in compression."""

    def test_compression_failure_restores_messages(self):
        """Verify that messages are restored when compression fails mid-way."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        # Simulate a model failure
        manager.model.response = MagicMock(side_effect=Exception("API Error"))

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            Message(role="assistant", content="Old answer", id="asst1", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
        ]

        original_message_ids = [msg.id for msg in messages]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = manager._compress_context(messages)

        # Compression should fail and return None
        assert result is None

        # Messages should be restored to original state
        assert len(messages) == 4
        assert [msg.id for msg in messages] == original_message_ids

    @pytest.mark.asyncio
    async def test_async_compression_failure_restores_messages(self):
        """Verify async compression restores messages on failure."""
        manager = CompressionManager(
            compress_context=True,
            model=MagicMock(),
        )

        # Simulate an async model failure
        manager.model.aresponse = AsyncMock(side_effect=Exception("API Error"))

        messages = [
            Message(role="system", content="System", id="sys1"),
            Message(role="user", content="Old question", id="user1", from_history=True),
            Message(role="assistant", content="Old answer", id="asst1", from_history=True),
            Message(role="user", content="Current question", id="user2", from_history=False),
        ]

        original_message_ids = [msg.id for msg in messages]

        with patch("agno.compression.manager.get_model", return_value=manager.model):
            result = await manager._acompress_context(messages)

        # Compression should fail and return None
        assert result is None

        # Messages should be restored to original state
        assert len(messages) == 4
        assert [msg.id for msg in messages] == original_message_ids
