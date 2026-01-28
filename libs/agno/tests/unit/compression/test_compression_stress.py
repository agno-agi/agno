"""
Aggressive stress tests for compression to find architectural bugs.

These tests target:
1. Race conditions in concurrent compression
2. Message list mutation during iteration
3. Stats thread-safety
4. Session persistence edge cases
5. Message ID handling edge cases
"""

import asyncio
from datetime import datetime
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.compression.context import CompressedContext
from agno.compression.manager import CompressionManager
from agno.models.message import Message


def create_mock_model(response_content: str = "Compressed summary"):
    """Create a mock model that passes get_model validation."""
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = response_content
    mock_model.response.return_value = mock_response
    mock_model.aresponse = AsyncMock(return_value=mock_response)
    mock_model.id = "test-model"
    mock_model.count_tokens = MagicMock(return_value=100)
    return mock_model


class TestConcurrentCompression:
    """Test race conditions in concurrent compression operations."""

    @pytest.mark.asyncio
    async def test_concurrent_context_compression_race_condition(self):
        """Multiple async compressions on same manager should not corrupt state."""
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        # Create multiple message lists
        message_lists = []
        for i in range(5):
            messages = [
                Message(role="system", content="System prompt"),
                Message(role="user", content=f"User {i}-1", from_history=True, id=f"u{i}-1"),
                Message(role="assistant", content=f"Response {i}-1", id=f"a{i}-1"),
                Message(role="user", content=f"User {i}-2", from_history=True, id=f"u{i}-2"),
                Message(role="assistant", content=f"Response {i}-2", id=f"a{i}-2"),
                Message(role="user", content=f"Current question {i}", from_history=False),
            ]
            message_lists.append(messages)

        # Run all compressions concurrently
        with patch("agno.compression.manager.get_model", return_value=mock_model):
            tasks = [manager.acompress(msgs) for msgs in message_lists]
            results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r is not None for r in results), "Some compressions failed"

        # Stats should be accurate (5 compressions)
        assert manager.stats.get("context_compressions") == 5

    @pytest.mark.asyncio
    async def test_concurrent_tool_compression_race_condition(self):
        """Multiple async tool compressions should not corrupt state."""
        mock_model = create_mock_model("Compressed tool result")

        manager = CompressionManager(
            model=mock_model,
            compress_tool_results=True,
            compress_tool_results_limit=2,
        )

        # Create multiple message lists with tool results
        message_lists = []
        for i in range(5):
            messages = [
                Message(role="user", content=f"Query {i}"),
                Message(role="assistant", content="", tool_calls=[{"id": f"t{i}"}]),
                Message(role="tool", content=f"Tool result {i}-1", tool_call_id=f"t{i}", tool_name="search"),
                Message(role="tool", content=f"Tool result {i}-2", tool_call_id=f"t{i}", tool_name="search"),
                Message(role="tool", content=f"Tool result {i}-3", tool_call_id=f"t{i}", tool_name="search"),
            ]
            message_lists.append(messages)

        # Run all compressions concurrently
        with patch("agno.compression.manager.get_model", return_value=mock_model):
            tasks = [manager.acompress(msgs) for msgs in message_lists]
            await asyncio.gather(*tasks)

        # Stats should reflect all compressions
        assert manager.stats.get("tool_compressions") == 5


class TestMessageMutation:
    """Test message list mutation edge cases."""

    def test_message_list_restored_on_compression_failure(self):
        """If compression fails, original messages must be restored."""
        mock_model = MagicMock()
        mock_model.response.side_effect = Exception("API Error")
        mock_model.id = "test-model"

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        original_messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="User 2", from_history=True, id="u2"),
            Message(role="assistant", content="Response 2", id="a2"),
            Message(role="user", content="Current", from_history=False),
        ]
        messages = original_messages.copy()
        original_len = len(messages)

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = manager._compress_context(messages)

        assert result is None
        # Messages should be restored to original length
        assert len(messages) == original_len

    @pytest.mark.asyncio
    async def test_async_message_list_restored_on_failure(self):
        """Async compression failure should also restore messages."""
        mock_model = MagicMock()
        mock_model.aresponse = AsyncMock(side_effect=Exception("API Error"))
        mock_model.id = "test-model"

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        original_messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="User 2", from_history=True, id="u2"),
            Message(role="assistant", content="Response 2", id="a2"),
            Message(role="user", content="Current", from_history=False),
        ]
        messages = original_messages.copy()
        original_len = len(messages)

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = await manager._acompress_context(messages)

        assert result is None
        assert len(messages) == original_len


class TestMessageIdEdgeCases:
    """Test edge cases with message IDs."""

    def test_messages_without_explicit_ids_get_auto_generated_ids(self):
        """Messages without explicit IDs get auto-generated UUIDs and are tracked."""
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        # Messages without explicit IDs - but Message auto-generates UUIDs
        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True),
            Message(role="assistant", content="Response 1"),
            Message(role="user", content="User 2", from_history=True),
            Message(role="assistant", content="Response 2"),
            Message(role="user", content="Current", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = manager._compress_context(messages)

        assert result is not None
        # All compressed messages have auto-generated IDs
        # 4 history messages (excluding system and current user)
        assert len(result.message_ids) == 4

    def test_explicit_ids_are_tracked(self):
        """Explicit message IDs are included in tracked set."""
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1"),  # Auto-generated UUID
            Message(role="user", content="User 2", from_history=True),  # Auto-generated UUID
            Message(role="assistant", content="Response 2", id="a2"),
            Message(role="user", content="Current", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = manager._compress_context(messages)

        assert result is not None
        # Explicit IDs should be in the set
        assert "u1" in result.message_ids
        assert "a2" in result.message_ids
        # 4 total (2 explicit + 2 auto-generated)
        assert len(result.message_ids) == 4

    def test_incremental_compression_skips_already_compressed(self):
        """Second compression should skip already-compressed messages."""
        mock_model = create_mock_model("Updated summary")

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        # Previous compression context
        prev_context = CompressedContext(
            content="Previous summary",
            message_ids={"u1", "a1"},
            updated_at=datetime.now(),
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),  # Already compressed
            Message(role="assistant", content="Response 1", id="a1"),  # Already compressed
            Message(role="user", content="User 2", from_history=True, id="u2"),  # New
            Message(role="assistant", content="Response 2", id="a2"),  # New
            Message(role="user", content="Current", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = manager._compress_context(messages, compression_context=prev_context)

        assert result is not None
        # Should include all message IDs (old + new)
        assert "u1" in result.message_ids
        assert "a1" in result.message_ids
        assert "u2" in result.message_ids
        assert "a2" in result.message_ids


class TestToolCompressionEdgeCases:
    """Test edge cases specific to tool compression."""

    def test_empty_tool_content_handling(self):
        """Tool messages with empty content should be handled gracefully."""
        mock_model = create_mock_model("Compressed")

        manager = CompressionManager(
            model=mock_model,
            compress_tool_results=True,
            compress_tool_results_limit=1,
        )

        messages = [
            Message(role="user", content="Query"),
            Message(role="assistant", content="", tool_calls=[{"id": "t1"}]),
            Message(role="tool", content="", tool_call_id="t1", tool_name="empty_tool"),  # Empty
        ]

        # Should not crash
        with patch("agno.compression.manager.get_model", return_value=mock_model):
            manager._compress_tools(messages)

    def test_already_compressed_tools_skipped(self):
        """Tools with compressed_content should not be recompressed."""
        mock_model = create_mock_model("Compressed")

        manager = CompressionManager(
            model=mock_model,
            compress_tool_results=True,
            compress_tool_results_limit=1,
        )

        messages = [
            Message(role="user", content="Query"),
            Message(role="assistant", content="", tool_calls=[{"id": "t1"}]),
            Message(
                role="tool",
                content="Original",
                compressed_content="Already compressed",  # Already has compressed
                tool_call_id="t1",
                tool_name="search",
            ),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            manager._compress_tools(messages)

        # Should not have been recompressed
        assert messages[2].compressed_content == "Already compressed"


class TestConflictingStrategies:
    """Test behavior when both compression strategies are enabled."""

    def test_both_strategies_enabled_defaults_to_context(self):
        """When both enabled, context compression takes precedence."""
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_tool_results=True,
            compress_context_messages_limit=3,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="Query", from_history=True, id="u1"),
            Message(role="assistant", content="", tool_calls=[{"id": "t1"}], id="a1"),
            Message(role="tool", content="Result", tool_call_id="t1", tool_name="search"),
            Message(role="user", content="Current", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = manager.compress(messages)

        # Context compression should run, not tool compression
        assert result is not None
        assert "context_compressions" in manager.stats
        # Tool should not be compressed individually
        assert "tool_compressions" not in manager.stats


class TestEmptyAndMinimalCases:
    """Test edge cases with empty or minimal message lists."""

    def test_empty_messages_list(self):
        """Empty message list should not crash."""
        manager = CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        )

        result = manager.compress([])
        assert result is None

    def test_single_message(self):
        """Single message should not trigger compression."""
        manager = CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        )

        messages = [Message(role="user", content="Hello")]
        result = manager.compress(messages)
        assert result is None

    def test_only_system_messages(self):
        """Only system messages should not crash."""
        manager = CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        )

        messages = [
            Message(role="system", content="System 1"),
            Message(role="system", content="System 2"),
        ]
        result = manager.compress(messages)
        assert result is None

    def test_no_current_user_message(self):
        """All history messages (no current user) should be handled."""
        manager = CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True),
            Message(role="assistant", content="Response 1"),
            Message(role="user", content="User 2", from_history=True),  # All from history
        ]

        result = manager.compress(messages)
        # Should return None since no current user message
        assert result is None


class TestTokenCounting:
    """Test token-based compression triggers."""

    def test_token_limit_triggers_compression(self):
        """Compression should trigger when token limit is exceeded."""
        mock_model = create_mock_model()
        mock_model.count_tokens.return_value = 5001  # Above limit

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_token_limit=5000,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="Current", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            result = manager.compress(messages)

        assert result is not None

    def test_token_limit_below_threshold_no_compression(self):
        """No compression when below token limit."""
        mock_model = create_mock_model()
        mock_model.count_tokens.return_value = 4999  # Below limit

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_token_limit=5000,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True),
            Message(role="assistant", content="Response 1"),
            Message(role="user", content="Current", from_history=False),
        ]

        result = manager.compress(messages)
        assert result is None


class TestModelStateManagement:
    """Test model assignment and state management."""

    def test_should_compress_does_not_mutate_model(self):
        """should_compress should NOT mutate self.model (query methods shouldn't have side effects)."""
        mock_model = create_mock_model()

        manager = CompressionManager(
            compress_context=True,
            compress_token_limit=5000,
        )

        messages = [Message(role="user", content="Test")]
        manager.should_compress(messages, model=mock_model)

        # Phase 2 fix: should_compress no longer mutates self.model
        assert manager.model is None

    def test_model_mutation_in_compress(self):
        """POTENTIAL BUG: Model mutation in _compress_context could cause issues."""
        mock_model = create_mock_model()

        # Start with no model
        manager = CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="Current", from_history=False),
        ]

        # Patch get_model to return our mock
        with patch("agno.compression.manager.get_model", return_value=mock_model):
            manager._compress_context(messages)

        # Model should now be set
        assert manager.model is not None


class TestStatsAccumulation:
    """Test that stats accumulate correctly across multiple compressions."""

    def test_stats_accumulate_correctly(self):
        """Stats should accumulate across multiple compression calls."""
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        for i in range(3):
            messages = [
                Message(role="system", content="System"),
                Message(role="user", content=f"User {i}", from_history=True, id=f"u{i}"),
                Message(role="assistant", content=f"Response {i}", id=f"a{i}"),
                Message(role="user", content="Current", from_history=False),
            ]
            with patch("agno.compression.manager.get_model", return_value=mock_model):
                manager._compress_context(messages)

        assert manager.stats.get("context_compressions") == 3


class TestPreviousSummaryIntegration:
    """Test incremental compression with previous summary."""

    def test_previous_summary_included_in_compression_prompt(self):
        """Previous summary should be passed to the compression model."""
        # Track the messages passed to response()
        captured_messages: List[Message] = []

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Updated summary"

        def capture_response(messages, **kwargs):
            captured_messages.extend(messages)
            return mock_response

        mock_model.response = capture_response
        mock_model.id = "test-model"

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        prev_context = CompressedContext(
            content="Previous facts: X, Y, Z",
            message_ids=set(),
            updated_at=datetime.now(),
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="Current", from_history=False),
        ]

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            manager._compress_context(messages, compression_context=prev_context)

        # Check that previous summary was included in the prompt
        assert len(captured_messages) == 2
        user_message = captured_messages[1].content
        assert "Previous summary" in user_message
        assert "Previous facts: X, Y, Z" in user_message


class TestArchitecturalBugs:
    """Tests specifically targeting potential architectural bugs."""

    def test_stats_not_thread_safe_potential_race(self):
        """
        ARCHITECTURAL BUG: Stats dict mutations are not thread-safe.

        The pattern `self.stats["key"] = self.stats.get("key", 0) + 1` is not atomic.
        Multiple concurrent compressions could lead to lost updates.
        """
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        # Run many compressions "sequentially" (simulating potential race)
        for i in range(100):
            messages = [
                Message(role="system", content="System"),
                Message(role="user", content=f"User {i}", from_history=True, id=f"u{i}"),
                Message(role="assistant", content=f"Response {i}", id=f"a{i}"),
                Message(role="user", content="Current", from_history=False),
            ]
            with patch("agno.compression.manager.get_model", return_value=mock_model):
                manager._compress_context(messages)

        # All 100 compressions should be counted
        assert manager.stats.get("context_compressions") == 100

    def test_model_mutation_side_effect(self):
        """
        ARCHITECTURAL CONCERN: self.model = get_model(self.model) mutates state.

        This could cause issues if:
        1. Multiple threads/coroutines access manager.model
        2. get_model returns a different instance
        """
        manager = CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        )

        mock_model_1 = create_mock_model("Summary 1")
        mock_model_2 = create_mock_model("Summary 2")

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="Current", from_history=False),
        ]

        # First compression with model 1
        with patch("agno.compression.manager.get_model", return_value=mock_model_1):
            manager._compress_context(messages.copy())

        # Manager's model should now be model 1
        assert manager.model == mock_model_1

        # Second compression with model 2
        with patch("agno.compression.manager.get_model", return_value=mock_model_2):
            manager._compress_context(messages.copy())

        # Manager's model changed! This could be unexpected
        assert manager.model == mock_model_2

    def test_message_list_modification_in_place(self):
        """
        ARCHITECTURAL CONCERN: messages[:] = new_messages modifies in place.

        If caller holds references to original messages, they'll see the change.
        """
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="User 1", from_history=True, id="u1"),
            Message(role="assistant", content="Response 1", id="a1"),
            Message(role="user", content="Current", from_history=False),
        ]

        # Keep a reference to the original list
        original_list = messages
        original_len = len(messages)

        with patch("agno.compression.manager.get_model", return_value=mock_model):
            manager._compress_context(messages)

        # The list was modified in place - original reference sees the change!
        # This is intentional but could be surprising
        assert len(original_list) < original_len
        assert original_list is messages  # Same list object

    def test_compression_context_message_ids_accumulation(self):
        """
        POTENTIAL MEMORY LEAK: message_ids set grows unboundedly.

        Over many compressions, the message_ids set could grow very large
        even though old messages are no longer relevant.
        """
        mock_model = create_mock_model()

        manager = CompressionManager(
            model=mock_model,
            compress_context=True,
            compress_context_messages_limit=3,
        )

        compression_context = None

        # Simulate 100 runs, each adding new message IDs
        for run in range(100):
            messages = [
                Message(role="system", content="System"),
                Message(role="user", content=f"User {run}", from_history=True, id=f"u_{run}"),
                Message(role="assistant", content=f"Response {run}", id=f"a_{run}"),
                Message(role="user", content="Current", from_history=False),
            ]

            with patch("agno.compression.manager.get_model", return_value=mock_model):
                result = manager._compress_context(messages, compression_context=compression_context)

            if result:
                compression_context = result

        # After 100 runs, we have 200 message IDs accumulated!
        # This is expected behavior but could be a memory concern for long sessions
        if compression_context:
            assert len(compression_context.message_ids) == 200  # 2 per run * 100 runs
