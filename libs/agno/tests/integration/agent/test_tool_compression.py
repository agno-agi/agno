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
def compression_agent(shared_db):
    """Agent with compression enabled and low threshold."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool, get_data],
        db=shared_db,
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=1),
        instructions="Use the tools as requested. Make multiple tool calls when asked.",
        telemetry=False,
    )


def test_compression_sync(compression_agent, shared_db):
    """Test compression: all tool messages compressed, content shorter, persists in session."""
    response = compression_agent.run(
        "First search for 'Python programming' and then search for 'JavaScript frameworks'"
    )

    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) >= 2, "Expected at least 2 tool calls"

    # ALL tool messages must be compressed
    for msg in tool_messages:
        assert msg.compressed_content is not None, "All tool messages should be compressed"
        assert len(str(msg.compressed_content)) < len(str(msg.content)), "Compressed content should be shorter"
        assert msg.get_content(use_compressed_content=True) == msg.compressed_content
        assert msg.get_content(use_compressed_content=False) == msg.content

    # Verify persistence in session
    session = compression_agent.get_session(compression_agent.session_id)
    assert session is not None, "Session should be retrievable"

    persisted_tool_messages = [m for r in session.runs for m in (r.messages or []) if m.role == "tool"]
    assert len(persisted_tool_messages) >= 2, "Persisted session should have 2+ tool messages"

    for msg in persisted_tool_messages:
        assert msg.compressed_content is not None, "Compressed content should persist in session"


@pytest.mark.asyncio
async def test_compression_async(shared_db):
    """Test compression works in async mode with all tool messages compressed."""
    # Create fresh instance to avoid event loop issues
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool, get_data],
        db=shared_db,
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=1),
        instructions="Use the tools as requested. Make multiple tool calls when asked.",
        telemetry=False,
    )

    response = await agent.arun("Search for 'Python async' and then search for 'asyncio patterns'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) >= 2, "Expected at least 2 tool calls"

    # ALL tool messages must be compressed
    for msg in tool_messages:
        assert msg.compressed_content is not None, "All tool messages should be compressed"
        assert len(str(msg.compressed_content)) < len(str(msg.content)), "Compressed content should be shorter"


def test_no_compression_when_disabled(shared_db):
    """Tool messages should NOT have compressed_content when compression is disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool],
        db=shared_db,
        compress_tool_results=False,
        instructions="Use the search tool.",
        telemetry=False,
    )

    response = agent.run("Search for 'test query'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    for msg in tool_messages:
        assert msg.compressed_content is None, "compressed_content should be None when compression is disabled"


def test_no_compression_below_threshold(shared_db):
    """Compression should not trigger when below threshold."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool],
        db=shared_db,
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=10),
        instructions="Use the search tool once.",
        telemetry=False,
    )

    response = agent.run("Search for 'single query'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    for msg in tool_messages:
        assert msg.compressed_content is None, "No compression should occur below threshold"
