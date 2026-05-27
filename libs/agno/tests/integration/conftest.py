import os
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import Engine, create_engine, text

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.session import Session
from agno.session.agent import AgentSession
from agno.session.workflow import WorkflowSession


@pytest.fixture(autouse=True)
def reset_async_client():
    """Reset global async HTTP client between tests to avoid event loop conflicts."""
    import agno.utils.http as http_utils

    # Reset before test
    http_utils._global_async_client = None
    yield
    # Reset after test
    http_utils._global_async_client = None


@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for agent storage testing."""
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
def shared_db(temp_storage_db_file):
    """Create a SQLite storage for sessions."""
    # Use a unique table name for each test run
    table_name = f"sessions_{uuid.uuid4().hex[:8]}"
    db = SqliteDb(session_table=table_name, db_file=temp_storage_db_file)
    return db


@pytest_asyncio.fixture
async def async_shared_db(temp_storage_db_file):
    """Create an async SQLite storage for sessions."""
    # Use a unique table name for each test run
    table_name = f"sessions_{uuid.uuid4().hex[:8]}"
    db = AsyncSqliteDb(session_table=table_name, db_file=temp_storage_db_file)

    # Initialize tables before using
    await db._create_all_tables()

    return db


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine"""
    engine = Mock(spec=Engine)
    return engine


@pytest.fixture
def mock_session():
    """Create a mock session"""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    return session


@pytest.fixture
def postgres_db(mock_engine) -> PostgresDb:
    """Create a PostgresDb instance with mock engine"""
    return PostgresDb(
        db_engine=mock_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


@pytest.fixture
def postgres_engine():
    """Create a PostgreSQL engine for testing using the actual database setup"""
    # Use the same connection string as the actual implementation
    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
    engine = create_engine(db_url)

    # Test connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()

    yield engine

    # Cleanup: Drop schema after tests
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS test_schema CASCADE"))
        conn.commit()


@pytest.fixture
def postgres_db_real(postgres_engine) -> PostgresDb:
    """Create PostgresDb with real PostgreSQL engine"""
    return PostgresDb(
        db_engine=postgres_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


@pytest.fixture
def sqlite_db_real(temp_storage_db_file) -> SqliteDb:
    """Create SQLiteDb with real SQLite engine"""
    return SqliteDb(
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
        db_file=temp_storage_db_file,
    )


@pytest.fixture
def image_path():
    return Path(__file__).parent / "res" / "images" / "golden_gate.png"


# -- Agent session fixtures --


@pytest.fixture
def session_with_explicit_name(test_agent: Agent):
    """Session with explicit session_name in session_data."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Hello, how are you?"),
            Message(role="assistant", content="I'm doing great!"),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-explicit-name",
        agent_id=test_agent.id,
        user_id="test-user",
        session_data={"session_name": "My Custom Session Name"},
        runs=[run],
    )


@pytest.fixture
def session_with_user_message(test_agent: Agent):
    """Session without session_name, should use first user message."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Hello, how are you?"),
            Message(role="assistant", content="I'm doing great!"),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-user-message",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run],
    )


@pytest.fixture
def session_with_fallback(test_agent: Agent):
    """Session where first run has no user message, should fallback to second run."""
    run1 = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="I'm doing great, thank you!"),
        ],
        created_at=int(time.time()) - 3600,
    )
    run2 = RunOutput(
        run_id="run-2",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="What is the weather?"),
            Message(role="assistant", content="It's sunny and 70 degrees Fahrenheit."),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-fallback",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run1, run2],
    )


@pytest.fixture
def session_empty_runs(test_agent: Agent):
    """Session with no runs."""
    return AgentSession(
        session_id="session-empty",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[],
    )


@pytest.fixture
def session_no_user_messages(test_agent: Agent):
    """Session with only assistant messages."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="Hello!"),
            Message(role="assistant", content="How can I help?"),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-no-user",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run],
    )


@pytest.fixture
def session_with_introduction(test_agent: Agent):
    """Session where assistant sends intro first, then user responds."""
    run = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="Hello! I'm your helpful assistant."),
            Message(role="user", content="What is the weather like?"),
            Message(role="assistant", content="It's sunny today."),
        ],
        created_at=int(time.time()),
    )
    return AgentSession(
        session_id="session-with-intro",
        agent_id=test_agent.id,
        user_id="test-user",
        runs=[run],
    )


# -- Workflow session fixtures --


@pytest.fixture
def workflow_session_with_string_input():
    """Workflow session with string input."""
    run = WorkflowRunOutput(
        run_id="workflow-run-1",
        workflow_id="test-workflow",
        status=RunStatus.completed,
        input="Generate a blog post about AI",
        created_at=int(time.time()),
    )
    return WorkflowSession(
        session_id="workflow-session-string",
        workflow_id="test-workflow",
        user_id="test-user",
        runs=[run],
    )


@pytest.fixture
def workflow_session_with_dict_input():
    """Workflow session with dict input."""
    run = WorkflowRunOutput(
        run_id="workflow-run-1",
        workflow_id="test-workflow",
        status=RunStatus.completed,
        input={"topic": "AI", "style": "formal"},
        created_at=int(time.time()),
    )
    return WorkflowSession(
        session_id="workflow-session-dict",
        workflow_id="test-workflow",
        user_id="test-user",
        runs=[run],
    )


@pytest.fixture
def workflow_session_empty_runs():
    """Workflow session with no runs."""
    return WorkflowSession(
        session_id="workflow-session-empty",
        workflow_id="test-workflow",
        user_id="test-user",
        runs=[],
    )


@pytest.fixture
def workflow_session_no_input():
    """Workflow session with run but no input."""
    run = WorkflowRunOutput(
        run_id="workflow-run-1",
        workflow_id="test-workflow",
        status=RunStatus.completed,
        created_at=int(time.time()),
    )
    return WorkflowSession(
        session_id="workflow-session-no-input",
        workflow_id="test-workflow",
        user_id="test-user",
        workflow_data={"name": "BlogGenerator"},
        runs=[run],
    )
