import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.openai import OpenAIChat
from agno.team.team import Team


def search_tool(query: str) -> str:
    """Search tool that returns large content to trigger compression."""
    return f"Search results for '{query}': " + ("This is detailed information about the query. " * 50)


def get_data(item: str) -> str:
    """Get data tool that returns large content."""
    return f"Data for '{item}': " + ("Comprehensive data entry with lots of details. " * 50)


@pytest.fixture
def dummy_member():
    """A minimal member agent with no tools (team leader will use its own tools)."""
    return Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )


@pytest.fixture
def compression_team(dummy_member, shared_db):
    """Team with tools directly on team leader and compression enabled."""
    return Team(
        name="CompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        tools=[search_tool, get_data],  # Tools directly on team leader
        db=shared_db,
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=1),
        instructions="Use YOUR OWN search_tool and get_data tools to answer questions. Do NOT delegate to members for search tasks.",
        telemetry=False,
    )


def test_compression_sync(compression_team, shared_db):
    """Test compression: team leader's tool messages compressed and content is shorter."""
    response = compression_team.run("Search for 'Python programming' and also search for 'JavaScript frameworks'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) >= 2, "Expected at least 2 tool calls"

    # ALL tool messages must be compressed
    for msg in tool_messages:
        assert msg.compressed_content is not None, "All tool messages should be compressed"
        assert len(str(msg.compressed_content)) < len(str(msg.content)), "Compressed content should be shorter"
        assert msg.get_content(use_compressed_content=True) == msg.compressed_content
        assert msg.get_content(use_compressed_content=False) == msg.content

    # Verify persistence in session
    session = compression_team.get_session(compression_team.session_id)
    assert session is not None, "Session should be retrievable"

    persisted_tool_messages = [m for r in session.runs for m in (r.messages or []) if m.role == "tool"]
    assert len(persisted_tool_messages) >= 2, "Persisted session should have 2+ tool messages"

    for msg in persisted_tool_messages:
        assert msg.compressed_content is not None, "Compressed content should persist in session"


@pytest.mark.asyncio
async def test_compression_async(shared_db):
    """Test compression works in async mode for team leader's tool calls."""
    # Create fresh instances to avoid event loop issues
    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team = Team(
        name="CompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        tools=[search_tool, get_data],  # Tools directly on team leader
        db=shared_db,
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=1),
        instructions="Use YOUR OWN search_tool and get_data tools to answer questions. Do NOT delegate to members for search tasks.",
        telemetry=False,
    )

    response = await team.arun("Search for 'Python async' and then search for 'asyncio patterns'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) >= 2, "Expected at least 2 tool calls"

    # ALL tool messages must be compressed
    for msg in tool_messages:
        assert msg.compressed_content is not None, "All tool messages should be compressed"
        assert len(str(msg.compressed_content)) < len(str(msg.content)), "Compressed content should be shorter"


def test_no_compression_when_disabled(shared_db):
    """Tool messages should NOT have compressed_content when compression is disabled."""
    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team = Team(
        name="NoCompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        tools=[search_tool],
        db=shared_db,
        compress_tool_results=False,
        instructions="Use YOUR OWN search_tool. Do NOT delegate.",
        telemetry=False,
    )

    response = team.run("Search for 'test query'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    for msg in tool_messages:
        assert msg.compressed_content is None, "compressed_content should be None when compression is disabled"


def test_no_compression_below_threshold(shared_db):
    """Compression should not trigger when below threshold."""
    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team = Team(
        name="ThresholdTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        tools=[search_tool],
        db=shared_db,
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=10),
        instructions="Use YOUR OWN search_tool once. Do NOT delegate.",
        telemetry=False,
    )

    response = team.run("Search for 'single query'")

    tool_messages = [m for m in response.messages if m.role == "tool"]
    for msg in tool_messages:
        assert msg.compressed_content is None, "No compression should occur below threshold"
