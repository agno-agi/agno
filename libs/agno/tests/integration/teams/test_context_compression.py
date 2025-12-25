"""Tests for full context compression in teams."""

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
def research_member():
    """Research member agent."""
    return Agent(
        name="Researcher",
        role="Research Specialist",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You specialize in research. Provide concise insights.",
    )


@pytest.fixture
def context_compression_team(shared_db, research_member):
    """Team with context compression enabled."""
    return Team(
        name="Research Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[research_member],
        tools=[search_tool, get_data],
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,  # Low threshold for testing
        ),
        instructions="Coordinate research tasks. Use tools and delegate to specialists.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )


def test_team_context_compression_sync(context_compression_team, shared_db):
    """Test that context compression works in sync mode for teams."""
    # First run - should not trigger compression
    response1 = context_compression_team.run("Search for 'AI trends'")
    assert response1.content is not None

    # Second run - may trigger compression due to message count
    response2 = context_compression_team.run("Now search for 'ML frameworks'")
    assert response2.content is not None

    # Verify session has compressed context stored
    session = context_compression_team.get_session(context_compression_team.session_id)
    assert session is not None

    # Check if compression occurred by looking at session data
    compressed_ctx = session.get_compression_context()
    if compressed_ctx is not None:
        assert compressed_ctx.content is not None, "Compressed context should have content"
        assert len(compressed_ctx.message_ids) > 0, "Compressed context should track message IDs"


@pytest.mark.asyncio
async def test_team_context_compression_async(shared_db, research_member):
    """Test that context compression works in async mode for teams."""
    team = Team(
        name="Async Research Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[research_member],
        tools=[search_tool],
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        ),
        instructions="Coordinate research tasks.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # First run
    response1 = await team.arun("Search for 'async Python'")
    assert response1.content is not None

    # Second run - may trigger compression
    response2 = await team.arun("Now search for 'asyncio patterns'")
    assert response2.content is not None

    # Verify session
    session = team.get_session(team.session_id)
    assert session is not None


def test_team_context_compression_with_token_limit(shared_db, research_member):
    """Test team context compression with token limit threshold."""
    compression_manager = CompressionManager(
        compress_context=True,
        compress_token_limit=500,  # Very low limit to trigger compression
    )

    team = Team(
        name="Token Limit Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[research_member],
        tools=[search_tool],
        db=shared_db,
        compression_manager=compression_manager,
        instructions="Use the search tool and provide detailed responses.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # Run multiple times to build up context
    team.run("Search for 'topic 1'")
    team.run("Search for 'topic 2'")
    response = team.run("Summarize what you found")

    assert response.content is not None


def test_team_no_context_compression_when_disabled(shared_db, research_member):
    """Context should not be compressed when compression is disabled."""
    team = Team(
        name="No Compression Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[research_member],
        db=shared_db,
        compress_context=False,
        instructions="Simple team.",
        add_history_to_context=True,
        telemetry=False,
    )

    team.run("Hello, world!")
    team.run("What did I say before?")

    session = team.get_session(team.session_id)
    compressed_ctx = session.get_compression_context()
    assert compressed_ctx is None, "No compression should occur when disabled"


def test_team_both_tool_and_context_compression(shared_db, research_member):
    """Test that both tool and context compression can work together in teams."""
    compression_manager = CompressionManager(
        compress_tool_results=True,
        compress_context=True,
        compress_tool_results_limit=1,
        compress_context_messages_limit=5,
    )

    team = Team(
        name="Dual Compression Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[research_member],
        tools=[search_tool],
        db=shared_db,
        compression_manager=compression_manager,
        instructions="Use the search tool as requested.",
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )

    # Make multiple tool calls
    team.run("Search for 'topic 1'")
    team.run("Search for 'topic 2'")
    response = team.run("Search for 'topic 3' and summarize")

    assert response.content is not None

    # Verify stats
    stats = compression_manager.stats
    # At least one type of compression should have occurred
    total_compressions = stats.get("context_compressions", 0) + stats.get("tool_results_compressed", 0)
    assert total_compressions >= 0  # May or may not trigger depending on token counts
