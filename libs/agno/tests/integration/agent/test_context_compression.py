import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.openai import OpenAIChat


def search_tool(query: str) -> str:
    """Search tool that returns large content to trigger compression."""
    return f"Search results for '{query}': " + ("This is detailed information about the query. " * 50)


def get_data(item: str) -> str:
    """Get data tool that returns large content."""
    return f"Data for '{item}': " + ("Comprehensive data entry with lots of details. " * 50)


@pytest.fixture
def context_compression_agent(shared_db):
    """Agent with context compression enabled."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool, get_data],
        db=shared_db,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,  # Low threshold for testing
        ),
        instructions="Use the tools as requested. Be thorough in your responses.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )


def test_context_compression_sync(context_compression_agent, shared_db):
    """Test that context compression works in sync mode."""
    # First run - should not trigger compression
    response1 = context_compression_agent.run("Search for 'Python programming'")
    assert response1.content is not None

    # Second run - may trigger compression due to message count
    response2 = context_compression_agent.run("Now search for 'JavaScript frameworks'")
    assert response2.content is not None

    # Verify session has compressed context stored
    session = context_compression_agent.get_session(context_compression_agent.session_id)
    assert session is not None

    # Verify compression occurred
    compressed_ctx = session.get_compression_context()
    assert compressed_ctx is not None, "Context compression should have occurred"
    assert compressed_ctx.content is not None, "Compressed context should have content"
    assert len(compressed_ctx.message_ids) > 0, "Compressed context should track message IDs"


@pytest.mark.asyncio
async def test_context_compression_async(shared_db):
    """Test that context compression works in async mode."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool, get_data],
        db=shared_db,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        ),
        instructions="Use the tools as requested.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # First run
    response1 = await agent.arun("Search for 'async Python'")
    assert response1.content is not None

    # Second run - may trigger compression
    response2 = await agent.arun("Now search for 'asyncio patterns'")
    assert response2.content is not None

    # Verify compression occurred
    session = agent.get_session(agent.session_id)
    assert session is not None
    compressed_ctx = session.get_compression_context()
    assert compressed_ctx is not None, "Context compression should have occurred"
    assert compressed_ctx.content is not None, "Compressed context should have content"
    assert len(compressed_ctx.message_ids) > 0, "Compressed context should track message IDs"


def test_context_compression_stream(context_compression_agent, shared_db):
    """Test that context compression works in sync streaming mode."""
    # First run - consume stream
    for _ in context_compression_agent.run("Search for 'Python programming'", stream=True):
        pass

    # Second run - consume stream
    for _ in context_compression_agent.run("Now search for 'JavaScript frameworks'", stream=True):
        pass

    # Verify compression occurred
    session = context_compression_agent.get_session(context_compression_agent.session_id)
    assert session is not None
    compressed_ctx = session.get_compression_context()
    assert compressed_ctx is not None, "Context compression should have occurred"
    assert compressed_ctx.content is not None, "Compressed context should have content"
    assert len(compressed_ctx.message_ids) > 0, "Compressed context should track message IDs"


@pytest.mark.asyncio
async def test_context_compression_async_stream(shared_db):
    """Test that context compression works in async streaming mode."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool, get_data],
        db=shared_db,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        ),
        instructions="Use the tools as requested.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # First run - consume async stream
    async for _ in agent.arun("Search for 'async Python'", stream=True):
        pass

    # Second run - consume async stream
    async for _ in agent.arun("Now search for 'asyncio patterns'", stream=True):
        pass

    # Verify compression occurred
    session = agent.get_session(agent.session_id)
    assert session is not None
    compressed_ctx = session.get_compression_context()
    assert compressed_ctx is not None, "Context compression should have occurred"
    assert compressed_ctx.content is not None, "Compressed context should have content"
    assert len(compressed_ctx.message_ids) > 0, "Compressed context should track message IDs"


def test_context_compression_with_token_limit(shared_db):
    """Test context compression with token limit threshold."""
    compression_manager = CompressionManager(
        compress_context=True,
        compress_token_limit=500,  # Very low limit to trigger compression
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool],
        db=shared_db,
        compression_manager=compression_manager,
        instructions="Use the search tool and provide detailed responses.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # Run multiple times to build up context
    agent.run("Search for 'Python basics'")
    agent.run("Search for 'Python advanced'")
    response = agent.run("Summarize what you found")

    assert response.content is not None

    # Verify compression occurred with low token limit
    assert compression_manager.stats.get("context_compressions", 0) > 0, "Context compression should have triggered"
    assert compression_manager.stats.get("original_context_tokens", 0) > compression_manager.stats.get(
        "compression_context_tokens", 0
    ), "Tokens should have been reduced"


def test_context_compression_preserves_continuity(shared_db):
    """Test that compression preserves conversation continuity."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,  # Very low for testing
        ),
        instructions="Remember facts from the conversation and refer back to them.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # Establish a fact
    agent.run("My name is Alice and I work at Acme Corp.")

    # Ask about the fact - should work even with compression
    response = agent.run("What is my name and where do I work?")

    # The response should contain the remembered information
    # (either from original context or compressed summary)
    assert response.content is not None


def test_no_context_compression_when_disabled(shared_db):
    """Context should not be compressed when compression is disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        compress_context=False,
        instructions="Simple agent.",
        add_history_to_context=True,
        telemetry=False,
    )

    agent.run("Hello, world!")
    agent.run("What did I say before?")

    session = agent.get_session(agent.session_id)
    compressed_ctx = session.get_compression_context()
    assert compressed_ctx is None, "No compression should occur when disabled"


def test_context_compression_takes_precedence(shared_db):
    """Test that context compression takes precedence over tool compression when both enabled."""
    compression_manager = CompressionManager(
        compress_tool_results=True,
        compress_context=True,
        compress_tool_results_limit=1,
        compress_context_messages_limit=5,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool],
        db=shared_db,
        compression_manager=compression_manager,
        instructions="Use the search tool as requested.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # Make multiple tool calls
    agent.run("Search for 'topic 1'")
    agent.run("Search for 'topic 2'")
    response = agent.run("Search for 'topic 3' and summarize all findings")

    assert response.content is not None

    # Verify context compression took precedence
    stats = compression_manager.stats
    assert stats.get("context_compressions", 0) > 0, "Context compression should have occurred"
    assert stats.get("original_context_tokens", 0) > stats.get("compression_context_tokens", 0), (
        "Tokens should have been reduced"
    )
