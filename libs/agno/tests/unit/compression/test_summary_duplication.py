"""Test to verify if summary duplication happens in compaction."""

from unittest.mock import MagicMock, patch

import pytest

from agno.compression.context import (
    SUMMARY_PREFIX,
    CompactionState,
    ContextCompactionManager,
)
from agno.models.message import Message
from agno.run.agent import RunOutput


class TestSummaryDuplication:
    """Test that summary messages are handled correctly across compactions."""

    def test_what_goes_into_summarize_call(self):
        """Trace exactly what messages go into the _summarize() call."""

        # Setup: Create a mock model that tracks what it receives
        mock_model = MagicMock()
        mock_model.count_tokens = MagicMock(return_value=60000)  # Over threshold

        captured_prompts = []

        def capture_response(messages):
            captured_prompts.append(messages)
            mock_response = MagicMock()
            mock_response.content = "New summary after second compaction"
            return mock_response

        mock_model.response = capture_response

        # Create manager - set model directly to avoid get_model() validation
        manager = ContextCompactionManager(
            model=None,  # Set to None first
            token_limit=50000,
            keep_recent=3,
        )
        manager.model = mock_model  # Then set mock directly

        # Create run_response with EXISTING compaction state (simulating after first compaction)
        existing_compaction = CompactionState(
            summary="First compaction summary: User wants to build an AI agent.",
            compacted_message_ids={"msg-1", "msg-2", "msg-3"},
            compacted_count=3,
            total_compactions=1,
        )
        run_response = RunOutput(
            run_id="test-run",
            agent_id="test-agent",
            session_id="test-session",
            compaction=existing_compaction,
        )

        # Build messages as _messages.py would do it:
        # 1. System message
        # 2. Injected summary (from get_summary_message())
        # 3. History (filtered, so no msg-1,2,3)
        # 4. Current user message

        injected_summary = existing_compaction.get_summary_message()
        print(f"\n=== Injected summary message ===")
        print(f"ID: {injected_summary.id}")
        print(f"Content starts with SUMMARY_PREFIX: {injected_summary.content.startswith(SUMMARY_PREFIX)}")
        print(f"Content: {injected_summary.content[:100]}...")

        messages = [
            Message(id="system-1", role="system", content="You are a helpful assistant."),
            injected_summary,  # This is what _messages.py injects
            # History (these would be user4, asst4, etc. - not compacted)
            Message(id="msg-4", role="user", content="Let's add database support"),
            Message(id="msg-5", role="assistant", content="Sure, I'll add PostgreSQL..."),
            Message(id="msg-6", role="user", content="Now add authentication"),
            Message(id="msg-7", role="assistant", content="Adding JWT auth..."),
            Message(id="msg-8", role="user", content="Test it please"),
            Message(id="msg-9", role="assistant", content="Running tests..."),
            Message(id="msg-10", role="user", content="Deploy to production"),
        ]

        print(f"\n=== Input messages to compact() ===")
        for m in messages:
            content_preview = str(m.content)[:50] if m.content else "None"
            print(f"  {m.role}: {content_preview}...")

        # Call compact with run_response (new API)
        result = manager.compact(messages, run_response=run_response)

        # Check what was sent to the LLM
        print(f"\n=== Messages sent to _summarize() LLM call ===")
        if captured_prompts:
            for i, msg in enumerate(captured_prompts[0]):
                content_preview = str(msg.content)[:80] if msg.content else "None"
                print(f"  [{i}] {msg.role}: {content_preview}...")

        # Analysis
        print(f"\n=== Analysis ===")
        if captured_prompts:
            prompt_msgs = captured_prompts[0]

            # Check if "Previous summary to update" is in there
            has_previous_summary_instruction = any("Previous summary to update" in str(m.content) for m in prompt_msgs)
            print(f"Has 'Previous summary to update' message: {has_previous_summary_instruction}")

            # Check if the injected summary content appears
            summary_content = "First compaction summary"
            count_summary_appearances = sum(1 for m in prompt_msgs if summary_content in str(m.content))
            print(f"Times summary content appears: {count_summary_appearances}")

            if count_summary_appearances > 1:
                print("⚠️  BUG CONFIRMED: Summary appears multiple times in LLM input!")
            else:
                print("✓ Summary appears only once")

        # Return result for inspection
        print(f"\n=== Output messages ===")
        for m in result.compacted_messages:
            content_preview = str(m.content)[:50] if m.content else "None"
            print(f"  {m.role}: {content_preview}...")

        return result, captured_prompts


if __name__ == "__main__":
    test = TestSummaryDuplication()
    result, prompts = test.test_what_goes_into_summarize_call()
