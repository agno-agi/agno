import os
import tempfile
import uuid

import pytest

from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.openai.chat import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team.team import Team


@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for team storage testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_memory_db_file():
    """Create a temporary SQLite database file for memory testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def team_storage(temp_storage_db_file):
    """Create a SQLite storage for team sessions."""
    # Use a unique table name for each test run
    table_name = f"team_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file, mode="team")
    storage.create()
    return storage


@pytest.fixture
def memory_db(temp_memory_db_file):
    """Create a SQLite memory database for testing."""
    db = SqliteMemoryDb(db_file=temp_memory_db_file)
    db.create()
    return db


@pytest.fixture
def memory(memory_db):
    """Create a Memory instance for testing."""
    return Memory(model=Claude(id="claude-3-5-sonnet-20241022"), db=memory_db)


@pytest.fixture
def web_agent():
    """Create a web agent for testing."""
    from agno.tools.duckduckgo import DuckDuckGoTools

    return Agent(
        name="Web Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Search the web for information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )


@pytest.fixture
def finance_agent():
    """Create a finance agent for testing."""
    from agno.tools.yfinance import YFinanceTools

    return Agent(
        name="Finance Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)],
    )


@pytest.fixture
def analysis_agent():
    """Create an analysis agent for testing."""
    return Agent(name="Analysis Agent", model=OpenAIChat(id="gpt-4o-mini"), role="Analyze data and provide insights")


@pytest.fixture
def route_team(web_agent, finance_agent, analysis_agent, team_storage, memory):
    """Create a route team with storage and memory for testing."""
    return Team(
        name="Route Team",
        mode="route",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[web_agent, finance_agent, analysis_agent],
        storage=team_storage,
        memory=memory,
        enable_user_memories=True,
    )


@pytest.mark.asyncio
async def test_multi_user_multi_session_route_team(route_team, team_storage, memory):
    """Test multi-user multi-session route team with storage and memory."""
    # Define user and session IDs
    user_1_id = "user_1@example.com"
    user_2_id = "user_2@example.com"
    user_3_id = "user_3@example.com"

    user_1_session_1_id = "user_1_session_1"
    user_1_session_2_id = "user_1_session_2"
    user_2_session_1_id = "user_2_session_1"
    user_3_session_1_id = "user_3_session_1"

    # Clear memory for this test
    memory.clear()

    # Team interaction with user 1 - Session 1
    await route_team.arun("What is the current stock price of AAPL?", user_id=user_1_id, session_id=user_1_session_1_id)
    await route_team.arun("What are the latest news about Apple?", user_id=user_1_id, session_id=user_1_session_1_id)

    # Team interaction with user 1 - Session 2
    await route_team.arun(
        "Compare the stock performance of AAPL with recent tech industry news",
        user_id=user_1_id,
        session_id=user_1_session_2_id,
    )

    # Team interaction with user 2
    await route_team.arun("What is the current stock price of MSFT?", user_id=user_2_id, session_id=user_2_session_1_id)
    await route_team.arun(
        "What are the latest news about Microsoft?", user_id=user_2_id, session_id=user_2_session_1_id
    )

    # Team interaction with user 3
    await route_team.arun(
        "What is the current stock price of GOOGL?", user_id=user_3_id, session_id=user_3_session_1_id
    )
    await route_team.arun("What are the latest news about Google?", user_id=user_3_id, session_id=user_3_session_1_id)

    # Continue the conversation with user 1
    await route_team.arun(
        "Based on the information you have, what stock would you recommend investing in?",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    # Verify storage DB has the right sessions
    all_session_ids = team_storage.get_all_session_ids()
    assert len(all_session_ids) == 4  # 4 sessions total

    # Check that each user has the expected sessions
    user_1_sessions = team_storage.get_all_sessions(user_id=user_1_id)
    assert len(user_1_sessions) == 2
    assert user_1_session_1_id in [session.session_id for session in user_1_sessions]
    assert user_1_session_2_id in [session.session_id for session in user_1_sessions]

    user_2_sessions = team_storage.get_all_sessions(user_id=user_2_id)
    assert len(user_2_sessions) == 1
    assert user_2_session_1_id in [session.session_id for session in user_2_sessions]

    user_3_sessions = team_storage.get_all_sessions(user_id=user_3_id)
    assert len(user_3_sessions) == 1
    assert user_3_session_1_id in [session.session_id for session in user_3_sessions]
