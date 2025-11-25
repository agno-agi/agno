import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.message import Message
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


@pytest.fixture
def compression_agent_no_db():
    """Agent with compression enabled but no database."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[search_tool, get_data],
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=1),
        instructions="Use the tools as requested. Make multiple tool calls when asked.",
        telemetry=False,
    )


def test_compression_sets_compressed_content_on_messages(compression_agent_no_db):
    """After run exceeding threshold, tool messages should have compressed_content."""
    response = compression_agent_no_db.run(
        "First search for 'Python programming' and then search for 'JavaScript frameworks'"
    )

    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) >= 1, "Expected at least one tool call"

    if len(tool_messages) >= 2:
        compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
        assert compressed_count > 0, "Expected some tool messages to be compressed when multiple tools are called"


def test_compressed_content_is_shorter(compression_agent_no_db):
    """Compressed content should generally be shorter than original."""
    response = compression_agent_no_db.run("Search for 'machine learning' and then get data for 'neural networks'")

    tool_messages = [m for m in response.messages if m.role == "tool"]

    for msg in tool_messages:
        if msg.compressed_content is not None:
            original_len = len(str(msg.content)) if msg.content else 0
            compressed_len = len(msg.compressed_content)
            assert compressed_len < original_len, (
                f"Compressed content ({compressed_len}) should be shorter than original ({original_len})"
            )


def test_compression_persists_in_session(compression_agent, shared_db):
    """compressed_content should be saved to and loaded from database."""
    compression_agent.run("Search for 'AI' then get data for 'deep learning'")

    session_id = compression_agent.session_id
    assert session_id is not None, "Agent should have a session_id"

    session = compression_agent.get_session(session_id)
    assert session is not None, "Session should be retrievable from database"
    assert session.runs is not None and len(session.runs) > 0, "Session should have runs"

    tool_messages = [m for r in session.runs for m in (r.messages or []) if m.role == "tool"]

    if len(tool_messages) >= 2:
        compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
        assert compressed_count > 0, "Compressed content should persist in session"


def test_compression_field_in_session_messages(compression_agent, shared_db):
    """Verify that compressed_content field exists in persisted messages."""
    compression_agent.run("Search for 'cloud computing'")

    session = compression_agent.get_session(compression_agent.session_id)
    assert session is not None

    all_messages = [m for r in session.runs for m in (r.messages or [])]
    tool_messages = [m for m in all_messages if m.role == "tool"]

    for msg in tool_messages:
        assert hasattr(msg, "compressed_content"), "Message should have compressed_content attribute"


@pytest.mark.asyncio
async def test_compression_async(compression_agent_no_db):
    """Compression should work in async mode."""
    response = await compression_agent_no_db.arun("Search for 'Python async' and then search for 'asyncio patterns'")

    tool_messages = [m for m in response.messages if m.role == "tool"]

    if len(tool_messages) >= 2:
        compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
        assert compressed_count > 0, "Async compression should work"


@pytest.mark.asyncio
async def test_compression_async_persistence(compression_agent, shared_db):
    """Compression should persist correctly in async mode."""
    await compression_agent.arun("Get data for 'databases' and search for 'SQL optimization'")

    session = compression_agent.get_session(compression_agent.session_id)
    assert session is not None, "Session should be retrievable after async run"

    tool_messages = [m for r in session.runs for m in (r.messages or []) if m.role == "tool"]

    if len(tool_messages) >= 2:
        compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
        assert compressed_count > 0, "Async compression should persist"


def test_compression_streaming(compression_agent_no_db):
    """Compression should work in streaming mode."""
    final_response = None
    for chunk in compression_agent_no_db.run(
        "Search for 'streaming data' then search for 'real-time processing'", stream=True
    ):
        final_response = chunk

    if final_response and hasattr(final_response, "messages") and final_response.messages:
        tool_messages = [m for m in final_response.messages if m.role == "tool"]
        if len(tool_messages) >= 2:
            compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
            assert compressed_count > 0, "Streaming compression should work"


@pytest.mark.asyncio
async def test_compression_async_streaming(compression_agent_no_db):
    """Compression should work in async streaming mode."""
    final_response = None
    async for chunk in compression_agent_no_db.arun(
        "Get data for 'microservices' and search for 'API design'", stream=True
    ):
        final_response = chunk

    if final_response and hasattr(final_response, "messages") and final_response.messages:
        tool_messages = [m for m in final_response.messages if m.role == "tool"]
        if len(tool_messages) >= 2:
            compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
            assert compressed_count > 0, "Async streaming compression should work"


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
    compressed_count = sum(1 for m in tool_messages if m.compressed_content is not None)
    assert compressed_count == 0, "No compression should occur below threshold"


def test_compressed_content_used_in_subsequent_calls(compression_agent_no_db):
    """Verify that after compression, get_content(use_compression=True) returns compressed version."""
    response = compression_agent_no_db.run("Search for 'artificial intelligence' then search for 'machine learning'")

    tool_messages = [m for m in response.messages if m.role == "tool"]

    for msg in tool_messages:
        if msg.compressed_content is not None:
            content_for_llm = msg.get_content(use_compression=True)
            assert content_for_llm == msg.compressed_content
            assert content_for_llm != msg.content
            assert len(str(content_for_llm)) < len(str(msg.content))


def test_get_content_returns_correct_version():
    """Verify get_content behavior with compression flag."""
    original = "This is a very long original content " * 100
    compressed = "Short summary"

    msg = Message(role="tool", content=original, compressed_content=compressed)

    assert msg.get_content(use_compression=False) == original
    assert msg.get_content(use_compression=True) == compressed


def test_messages_have_compressed_content_for_llm(compression_agent_no_db):
    """Verify that messages passed to LLM would contain compressed content."""
    response = compression_agent_no_db.run("Get data for 'databases' then search for 'NoSQL'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    messages_with_compression = [m for m in tool_messages if m.compressed_content is not None]

    if len(tool_messages) >= 2:
        assert len(messages_with_compression) > 0, "Expected compression to be applied to some messages"

        for msg in messages_with_compression:
            llm_content = msg.get_content(use_compression=True)
            assert llm_content == msg.compressed_content
            assert len(llm_content) < len(str(msg.content))
