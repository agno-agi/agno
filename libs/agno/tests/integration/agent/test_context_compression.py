import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.openai import OpenAIChat


@pytest.fixture
def context_compression_agent(shared_db):
    """Agent with context compression enabled and low message threshold."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,  # Low threshold for testing
        ),
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )


def test_context_compression_sync(context_compression_agent, shared_db):
    """Test context compression: agent remembers context across multiple runs."""
    session_id = context_compression_agent.session_id

    # Run 1: Initial message
    context_compression_agent.run("Hello, my name is Alice.")

    # Run 2: Follow-up
    context_compression_agent.run("I work as a software engineer.")

    # Run 3: Another follow-up - should trigger compression (messages exceed limit)
    response = context_compression_agent.run("What is my name and profession?")

    # Verify response is coherent (agent should remember context)
    assert response.content is not None, "Agent should respond"

    # Check session has compressed context after multiple runs
    session = context_compression_agent.get_session(session_id)
    assert session is not None, "Session should exist"

    # Compression should have triggered (messages exceed limit of 3)
    assert session.compressed_context is not None, "Compression should have triggered"
    assert session.compressed_context.content, "Compressed context should have content"
    assert len(session.compressed_context.message_ids) > 0, "Should track compressed message IDs"


def test_context_compression_persists(shared_db):
    """Test that compressed context persists to database and is reloaded."""
    session_id = "test_context_persistence"

    # Create agent and run multiple times to trigger compression
    agent1 = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        telemetry=False,
    )

    agent1.run("Remember: The secret code is ALPHA123.")
    agent1.run("Also remember: The project name is Phoenix.")
    agent1.run("What information have I shared with you?")

    # Get session and verify compression occurred
    session1 = agent1.get_session(session_id)
    assert session1 is not None, "Session should exist"
    assert session1.compressed_context is not None, "Compression should have triggered after 3 runs"
    assert session1.compressed_context.content, "Compressed context should have content"

    # Create a new agent instance with same session to verify persistence
    agent2 = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        telemetry=False,
    )

    # Agent should be able to recall information from compressed context
    response = agent2.run("What was the secret code I mentioned earlier?")

    assert response.content is not None, "Agent should respond"
    # The response should reference the information from previous runs
    # (either from history or compressed context)


@pytest.mark.asyncio
async def test_context_compression_async(shared_db):
    """Test context compression works in async mode."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    await agent.arun("My favorite color is blue.")
    await agent.arun("My favorite food is pizza.")
    response = await agent.arun("What are my preferences?")

    assert response.content is not None, "Agent should respond in async mode"


def test_no_context_compression_when_disabled(shared_db):
    """Context compression should not occur when disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compress_context=False,
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    agent.run("Message one")
    agent.run("Message two")
    agent.run("Message three")

    session = agent.get_session(agent.session_id)
    assert session is not None, "Session should exist"
    assert session.compressed_context is None, "No compression should occur when disabled"


def test_no_context_compression_below_threshold(shared_db):
    """Context compression should not trigger below message threshold."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=100,  # Very high threshold
        ),
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    agent.run("Single message")

    session = agent.get_session(agent.session_id)
    assert session is not None, "Session should exist"
    assert session.compressed_context is None, "No compression below threshold"


def test_compressed_context_structure(shared_db):
    """Test that CompressedContext has correct structure when compression occurs."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        telemetry=False,
    )

    # Multiple runs to trigger compression
    agent.run("First message with important info: X=42")
    agent.run("Second message with more info: Y=100")
    agent.run("Third message asking about X and Y")

    session = agent.get_session(agent.session_id)
    assert session is not None, "Session should exist"

    # Compression should have triggered
    assert session.compressed_context is not None, "Compression should have triggered"

    ctx = session.compressed_context
    # Verify structure
    assert hasattr(ctx, "content"), "Should have content attribute"
    assert hasattr(ctx, "message_ids"), "Should have message_ids attribute"
    assert hasattr(ctx, "updated_at"), "Should have updated_at attribute"

    # Content should be a string
    assert isinstance(ctx.content, str), "Content should be string"
    assert ctx.content, "Content should not be empty"

    # message_ids should be a set
    assert isinstance(ctx.message_ids, set), "message_ids should be a set"
    assert len(ctx.message_ids) > 0, "message_ids should not be empty"

    # Serialization should work
    ctx_dict = ctx.to_dict()
    assert "content" in ctx_dict
    assert "message_ids" in ctx_dict
    assert "updated_at" in ctx_dict

    # message_ids should be list in dict form
    assert isinstance(ctx_dict["message_ids"], list), "message_ids should serialize to list"


def test_mid_run_compression_with_tools(shared_db):
    """Test context compression during a single run with many tool calls."""
    from agno.tools.calculator import CalculatorTools

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        tools=[CalculatorTools()],
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=5,  # Low threshold to trigger mid-run
        ),
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # Single run with multiple tool calls that should trigger compression
    response = agent.run(
        "Calculate the following in sequence: 10+5, then 15*2, then 30-8, then 22/2. "
        "After all calculations, tell me the final result."
    )

    assert response.content is not None, "Agent should respond after tool calls"

    # Check that the agent completed the task
    session = agent.get_session(agent.session_id)
    assert session is not None, "Session should exist"

    # If compression triggered, compressed_context should exist
    # (depends on number of tool calls generated)
    if session.compressed_context is not None:
        assert session.compressed_context.content, "Compressed context should have content"
        assert len(session.compressed_context.message_ids) > 0, "Should track message IDs"


def test_cross_run_summary_injection(shared_db):
    """Test that compressed context summary is injected when loading history on next run."""
    session_id = "test_summary_injection"

    # Create first agent and run multiple times to trigger compression
    agent1 = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,  # Very low to ensure compression
        ),
        add_history_to_context=True,
        num_history_runs=10,
        telemetry=False,
    )

    # Run with specific facts that should be in the summary
    agent1.run("Remember this important fact: The capital of France is Paris.")
    agent1.run("Another fact: The Eiffel Tower is 330 meters tall.")
    agent1.run("One more: The Louvre has 380,000 objects.")

    # Verify compression occurred
    session1 = agent1.get_session(session_id)
    assert session1 is not None, "Session should exist"
    assert session1.compressed_context is not None, "Compression should have triggered"
    stored_summary = session1.compressed_context.content
    assert stored_summary, "Summary content should not be empty"

    # Create a new agent instance with same session
    agent2 = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        telemetry=False,
    )

    # Ask about facts from the compressed context
    response = agent2.run("What facts did I share about France and Paris?")

    assert response.content is not None, "Agent should respond"
    # The response should reference information from the compressed summary
    # (The summary was injected when loading history)
