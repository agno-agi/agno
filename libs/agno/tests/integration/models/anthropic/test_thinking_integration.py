"""
Integration test for Claude thinking content storage with real API calls
"""

import json
import os
import shutil
import tempfile

import pytest

from agno.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.anthropic import Claude
from agno.storage.json import JsonStorage


# @pytest.mark.skipif(
#     not os.getenv("ANTHROPIC_API_KEY"),
#     reason="ANTHROPIC_API_KEY not set"
# )
class TestClaudeThinkingIntegration:
    """Integration tests for Claude thinking content with real API calls"""

    async def test_thinking_content_stored_with_json_storage(self):
        """Test that thinking content from real Claude API calls is stored in JSON storage"""

        # Check if API key is set
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        # Create temporary directory for storage
        storage_dir = tempfile.mkdtemp()

        try:
            # Create agent with Claude thinking model and JSON storage
            agent = Agent(
                model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
                storage=JsonStorage(dir_path=storage_dir),
                memory=Memory(),
                user_id="test_user_thinking",
                session_id="test_session_thinking",
                debug_mode=True,
            )

            # Ask a question that should trigger thinking
            response = await agent.arun(
                "Think step by step: What is 25 * 47? Show your reasoning process.",
                stream=False,  # Use non-streaming for simpler testing first
            )

            # Verify response has thinking content
            assert response.thinking is not None, "Response should contain thinking content"
            assert len(response.thinking) > 0, "Thinking content should not be empty"
            print(f"✅ Received thinking content: {response.thinking[:100]}...")

            # Read the storage files to verify thinking was persisted
            session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

            session_found = False
            thinking_persisted = False

            for session_file in session_files:
                if session_file == "test_session_thinking.json":
                    session_found = True

                    with open(os.path.join(storage_dir, session_file), "r") as f:
                        session_data = json.load(f)

                    # Check messages in this session - they're stored in memory.runs[].messages[]
                    if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                        for run in session_data["memory"]["runs"]:
                            if "messages" in run:
                                for message in run["messages"]:
                                    if message.get("role") == "assistant" and message.get("thinking"):
                                        thinking_persisted = True
                                        thinking_content = message["thinking"]

                                        # Verify thinking content contains mathematical reasoning
                                        assert len(thinking_content) > 50, "Thinking content should be substantial"
                                        print(f"✅ Thinking content persisted to storage: {thinking_content[:100]}...")

                                        # Check if provider_data with signature is stored
                                        if message.get("provider_data") and message["provider_data"].get("signature"):
                                            print(
                                                f"✅ Thinking signature preserved: {message['provider_data']['signature']}"
                                            )

                                        break
                            if thinking_persisted:
                                break
                    break

            assert session_found, "Session should be found in storage"
            assert thinking_persisted, "Thinking content should be persisted in storage"

        finally:
            # Clean up temporary directory
            if os.path.exists(storage_dir):
                shutil.rmtree(storage_dir)

    async def test_thinking_content_with_streaming(self):
        """Test thinking content capture during streaming responses"""

        # Check if API key is set
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        # Create temporary directory for storage
        storage_dir = tempfile.mkdtemp()

        try:
            # Create agent with streaming enabled
            agent = Agent(
                model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
                storage=JsonStorage(dir_path=storage_dir),
                memory=Memory(),
                user_id="test_user_streaming",
                session_id="test_session_streaming",
                debug_mode=True,
            )

            # Run with streaming to test ContentBlockStopEvent handling
            stream_response = await agent.arun(
                "Analyze this problem step by step: If a train travels 60 mph for 2.5 hours, how far does it go?",
                stream=True,
            )

            # Collect final response from stream
            final_response = None
            thinking_chunks = []

            async for chunk in stream_response:
                if hasattr(chunk, "content") and chunk.content:
                    # Collect any thinking content from streaming chunks
                    if hasattr(chunk, "thinking") and chunk.thinking:
                        thinking_chunks.append(chunk.thinking)

                # Look for the completed run event which contains the final response
                if (
                    hasattr(chunk, "event")
                    and chunk.event == "RunCompleted"
                    and hasattr(chunk, "run_response")
                    and chunk.run_response
                ):
                    final_response = chunk.run_response
                # Also check if this chunk itself is the final response
                elif hasattr(chunk, "thinking") and chunk.thinking:
                    final_response = chunk

            # Verify we got a final response with thinking
            assert final_response is not None, "Should receive final response"
            assert final_response.thinking is not None, "Final response should have thinking content"
            print(f"✅ Streaming response thinking: {final_response.thinking[:100]}...")

            # Verify storage contains the thinking content
            session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

            thinking_found = False
            for session_file in session_files:
                if session_file == "test_session_streaming.json":
                    with open(os.path.join(storage_dir, session_file), "r") as f:
                        session_data = json.load(f)

                    # Check messages in memory.runs[].messages[]
                    if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                        for run in session_data["memory"]["runs"]:
                            if "messages" in run:
                                for message in run["messages"]:
                                    if (
                                        message.get("role") == "assistant"
                                        and message.get("thinking")
                                        and len(message["thinking"]) > 20
                                    ):
                                        thinking_found = True
                                        print(f"✅ Streaming thinking content stored: {message['thinking'][:100]}...")
                                        break
                            if thinking_found:
                                break
                    break

            assert thinking_found, "Thinking content from streaming should be stored"

        finally:
            # Clean up
            if os.path.exists(storage_dir):
                shutil.rmtree(storage_dir)

    async def test_thinking_content_with_memory_retrieval(self):
        """Test that thinking content can be retrieved from memory in subsequent conversations"""

        # Check if API key is set
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        storage_dir = tempfile.mkdtemp()

        try:
            # First conversation - store thinking content
            agent1 = Agent(
                model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
                storage=JsonStorage(dir_path=storage_dir),
                memory=Memory(),
                user_id="test_user_memory",
                session_id="test_session_memory",
                debug_mode=True,
            )

            response1 = await agent1.arun("Think through this: What are the prime factors of 84?", stream=False)

            assert response1.thinking is not None, "First response should have thinking"
            print(f"✅ First conversation thinking: {response1.thinking[:100]}...")

            # Second conversation - verify thinking content is accessible
            agent2 = Agent(
                model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
                storage=JsonStorage(dir_path=storage_dir),
                memory=Memory(),
                user_id="test_user_memory",  # Same user
                session_id="test_session_memory",  # Same session
                add_history_to_messages=True,  # Enable history
            )

            # Read from storage to load the session with thinking content
            agent2.read_from_storage(session_id="test_session_memory")

            # Get memory messages to verify thinking content is preserved
            messages = agent2.memory.get_messages_for_session(session_id="test_session_memory")

            thinking_in_memory = False
            for msg in messages:
                if msg.role == "assistant" and msg.thinking:
                    thinking_in_memory = True
                    print(f"✅ Thinking content retrieved from memory: {msg.thinking[:100]}...")

                    # Verify provider_data is also preserved
                    if hasattr(msg, "provider_data") and msg.provider_data:
                        print(f"✅ Provider data preserved in memory: {msg.provider_data}")
                    break

            assert thinking_in_memory, "Thinking content should be retrievable from memory"

        finally:
            if os.path.exists(storage_dir):
                shutil.rmtree(storage_dir)

    async def test_thinking_signature_preservation(self):
        """Test that thinking signatures are properly preserved through the entire flow"""

        # Check if API key is set
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        storage_dir = tempfile.mkdtemp()

        try:
            agent = Agent(
                model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
                storage=JsonStorage(dir_path=storage_dir),
                memory=Memory(),
                user_id="test_user_signature",
                session_id="test_session_signature",
                debug_mode=True,
            )

            response = await agent.arun(
                "Reason through this logic puzzle: If all cats are animals, and some animals are dogs, can we conclude that some cats are dogs?",
                stream=False,
            )

            # Verify response has thinking
            assert response.thinking is not None, "Response should have thinking content"

            # Check if provider_data contains signature
            if hasattr(response, "provider_data") and response.provider_data:
                signature = response.provider_data.get("signature")
                if signature:
                    print(f"✅ Response contains thinking signature: {signature}")

                    # Verify signature is preserved in storage
                    session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

                    signature_preserved = False
                    for session_file in session_files:
                        if session_file == "test_session_signature.json":
                            with open(os.path.join(storage_dir, session_file), "r") as f:
                                session_data = json.load(f)

                            # Check messages in memory.runs[].messages[]
                            if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                                for run in session_data["memory"]["runs"]:
                                    if "messages" in run:
                                        for message in run["messages"]:
                                            if (
                                                message.get("role") == "assistant"
                                                and message.get("provider_data")
                                                and message["provider_data"].get("signature") == signature
                                            ):
                                                signature_preserved = True
                                                print(f"✅ Signature preserved in storage: {signature}")
                                                break
                                    if signature_preserved:
                                        break
                            break

                    assert signature_preserved, "Thinking signature should be preserved in storage"
                else:
                    print("ℹ️ No signature in response provider_data (this is optional)")
            else:
                print("ℹ️ No provider_data in response (this is optional)")

        finally:
            if os.path.exists(storage_dir):
                shutil.rmtree(storage_dir)

    async def test_thinking_content_with_message_array(self):
        """Test sending an array of messages where assistant message has content=None but thinking and signature"""

        # Check if API key is set
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        storage_dir = tempfile.mkdtemp()

        try:
            agent = Agent(
                model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
                storage=JsonStorage(dir_path=storage_dir),
                memory=Memory(),
                user_id="test_user_messages",
                session_id="test_session_messages",
                debug_mode=True,
            )

            # Create a message array with an assistant message that has thinking but no content
            messages = [
                {"role": "user", "content": "What is 15 + 27?"},
                {
                    "role": "assistant",
                    "content": None,  # No content
                    "thinking": "I need to add 15 and 27. 15 + 27 = 42.",
                    "provider_data": {"signature": "test_signature_12345"},
                },
                {"role": "user", "content": "Now what is that result multiplied by 2?"},
            ]

            # Send the message array to the agent
            response = await agent.arun(messages=messages, stream=False)

            # Verify we got a response
            assert response is not None, "Should receive response"
            assert response.content is not None, "Response should have content"
            print(f"✅ Response to follow-up question: {response.content[:100]}...")

            # If this response also has thinking, check it
            if response.thinking:
                print(f"✅ New thinking content: {response.thinking[:100]}...")

            # Verify the original thinking content with None content is preserved in storage
            session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

            none_content_thinking_found = False

            for session_file in session_files:
                if session_file == "test_session_messages.json":
                    with open(os.path.join(storage_dir, session_file), "r") as f:
                        session_data = json.load(f)

                    # Check messages in memory.runs[].messages[]
                    if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                        for run in session_data["memory"]["runs"]:
                            if "messages" in run:
                                for message in run["messages"]:
                                    if (
                                        message.get("role") == "assistant"
                                        and message.get("content") is None
                                        and message.get("thinking") == "I need to add 15 and 27. 15 + 27 = 42."
                                    ):
                                        none_content_thinking_found = True
                                        print("✅ Assistant message with content=None and thinking preserved")

                                        # Check if signature is preserved
                                        if (
                                            message.get("provider_data")
                                            and message["provider_data"].get("signature") == "test_signature_12345"
                                        ):
                                            print("✅ Signature preserved in None-content thinking message")

                                    elif (
                                        message.get("role") == "assistant"
                                        and message.get("content") is not None
                                        and message.get("thinking")
                                    ):
                                        print(f"✅ New assistant response with thinking: {message['thinking'][:50]}...")
                    break

            assert none_content_thinking_found, "Assistant message with content=None and thinking should be preserved"
            print("✅ Test passed: Messages with content=None but thinking are handled correctly")

        finally:
            if os.path.exists(storage_dir):
                shutil.rmtree(storage_dir)
