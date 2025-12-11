import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.openai import OpenAIChat
from agno.team.team import Team


@pytest.fixture
def dummy_member():
    """A minimal member agent."""
    return Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )


@pytest.fixture
def context_compression_team(dummy_member, shared_db):
    """Team with context compression enabled and low message threshold."""
    return Team(
        name="CompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=3,
        ),
        add_history_to_context=True,
        num_history_runs=5,
        instructions="Answer questions directly without delegating to members unless necessary.",
        telemetry=False,
    )


def test_context_compression_sync(context_compression_team, shared_db):
    """Test context compression: team remembers context across multiple runs."""
    session_id = context_compression_team.session_id

    # Run 1: Initial message
    context_compression_team.run("Hello, my name is Bob.")

    # Run 2: Follow-up
    context_compression_team.run("I am interested in machine learning.")

    # Run 3: Another follow-up - should trigger compression
    response = context_compression_team.run("What is my name and interest?")

    assert response.content is not None, "Team should respond"

    # Check session has compressed context after multiple runs
    session = context_compression_team.get_session(session_id)
    assert session is not None, "Session should exist"

    # Compression should have triggered (messages exceed limit of 3)
    compressed_ctx = session.get_compressed_context()
    assert compressed_ctx is not None, "Compression should have triggered"
    assert compressed_ctx.content, "Compressed context should have content"
    assert len(compressed_ctx.message_ids) > 0, "Should track compressed message IDs"


def test_context_compression_persists(shared_db):
    """Test that team compressed context persists across instances."""
    session_id = "test_team_context_persistence"

    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    # Create team and run multiple times
    team1 = Team(
        name="CompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        db=shared_db,
        session_id=session_id,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    team1.run("The password is SECRET789.")
    team1.run("The server name is Apollo.")
    team1.run("Summarize what I told you.")

    # Verify compression occurred
    session1 = team1.get_session(session_id)
    assert session1 is not None, "Session should exist"
    compressed_ctx1 = session1.get_compressed_context()
    assert compressed_ctx1 is not None, "Compression should have triggered after 3 runs"
    assert compressed_ctx1.content, "Compressed context should have content"

    # Create new team with same session
    dummy_member2 = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team2 = Team(
        name="CompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member2],
        db=shared_db,
        session_id=session_id,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    response = team2.run("What was the password I mentioned?")
    assert response.content is not None, "Team should respond"


@pytest.mark.asyncio
async def test_context_compression_async(shared_db):
    """Test context compression works in async mode."""
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
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=5,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    await team.arun("My pet is a dog named Max.")
    await team.arun("Max is 3 years old.")
    response = await team.arun("Tell me about my pet.")

    assert response.content is not None, "Team should respond in async mode"


def test_no_context_compression_when_disabled(shared_db):
    """Context compression should not occur when disabled."""
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
        db=shared_db,
        compress_context=False,
        add_history_to_context=True,
        num_history_runs=5,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    team.run("Message one")
    team.run("Message two")
    team.run("Message three")

    session = team.get_session(team.session_id)
    assert session is not None, "Session should exist"
    assert session.get_compressed_context() is None, "No compression when disabled"


def test_no_context_compression_below_threshold(shared_db):
    """Context compression should not trigger below threshold."""
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
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=100,  # Very high threshold
        ),
        add_history_to_context=True,
        num_history_runs=5,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    team.run("Single message")

    session = team.get_session(team.session_id)
    assert session is not None, "Session should exist"
    assert session.get_compressed_context() is None, "No compression below threshold"


def test_compressed_context_structure(shared_db):
    """Test that CompressedContext has correct structure when compression occurs."""
    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team = Team(
        name="StructureTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=10,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    # Multiple runs to trigger compression
    team.run("First message with important info: X=42")
    team.run("Second message with more info: Y=100")
    team.run("Third message asking about X and Y")

    session = team.get_session(team.session_id)
    assert session is not None, "Session should exist"

    # Compression should have triggered
    ctx = session.get_compressed_context()
    assert ctx is not None, "Compression should have triggered"
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


def test_context_compression_sync_stream(shared_db):
    """Test context compression works with sync streaming for Team."""
    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team = Team(
        name="StreamCompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=5,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    # Use run with stream=True to test streaming path
    team.run("My favorite sport is basketball.", stream=True)
    team.run("I play every weekend.", stream=True)
    response = team.run("What do you know about my hobbies?", stream=True)

    assert response.content is not None, "Team should respond in sync stream mode"

    # Verify compression occurred
    session = team.get_session(team.session_id)
    assert session is not None, "Session should exist"
    compressed_ctx = session.get_compressed_context()
    assert compressed_ctx is not None, "Compression should have triggered in streaming mode"
    assert compressed_ctx.content, "Compressed context should have content"


@pytest.mark.asyncio
async def test_context_compression_async_stream(shared_db):
    """Test context compression works with async streaming for Team."""
    dummy_member = Agent(
        name="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You assist with general questions.",
        telemetry=False,
    )

    team = Team(
        name="AsyncStreamCompressionTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[dummy_member],
        db=shared_db,
        compress_context=True,
        compression_manager=CompressionManager(
            compress_context=True,
            compress_context_messages_limit=2,
        ),
        add_history_to_context=True,
        num_history_runs=5,
        instructions="Answer questions directly.",
        telemetry=False,
    )

    # Use arun with stream=True to test async streaming path
    await team.arun("I live in New York City.", stream=True)
    await team.arun("I have lived here for 5 years.", stream=True)
    response = await team.arun("Where do I live and for how long?", stream=True)

    assert response.content is not None, "Team should respond in async stream mode"

    # Verify compression occurred
    session = team.get_session(team.session_id)
    assert session is not None, "Session should exist"
    compressed_ctx = session.get_compressed_context()
    assert compressed_ctx is not None, "Compression should have triggered in async streaming mode"
    assert compressed_ctx.content, "Compressed context should have content"
