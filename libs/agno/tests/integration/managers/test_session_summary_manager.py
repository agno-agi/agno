import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.agent import Message, RunOutput
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.summary import SessionSummary, SessionSummaryManager, SessionSummaryResponse
from agno.session.team import TeamSession


@pytest.fixture
def temp_db_file():
    """Create a temporary SQLite database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def session_db(temp_db_file):
    """Create a SQLite session database for testing."""
    db = SqliteDb(db_file=temp_db_file)
    return db


@pytest.fixture
def model():
    """Create an OpenAI model for testing."""
    return OpenAIChat(id="gpt-4o-mini")


@pytest.fixture
def session_summary_manager(model):
    """Create a SessionSummaryManager instance for testing."""
    return SessionSummaryManager(model=model)


@pytest.fixture
def mock_agent_session():
    """Create a mock agent session with sample messages."""
    session = Mock(spec=AgentSession)
    session.get_messages.return_value = [
        Message(role="user", content="Hello, I need help with Python programming."),
        Message(
            role="assistant",
            content="I'd be happy to help you with Python! What specific topic would you like to learn about?",
        ),
        Message(role="user", content="I want to learn about list comprehensions."),
        Message(
            role="assistant",
            content="List comprehensions are a concise way to create lists in Python. Here's the basic syntax: [expression for item in iterable if condition].",
        ),
        Message(role="user", content="Can you give me an example?"),
        Message(
            role="assistant",
            content="Sure! Here's an example: squares = [x**2 for x in range(10)] creates a list of squares from 0 to 81.",
        ),
    ]
    session.summary = None
    return session


@pytest.fixture
def agent_session_with_db():
    """Create an agent session with sample runs and messages."""
    from agno.run.base import RunStatus

    # Create sample messages
    messages1 = [
        Message(role="user", content="Hello, I need help with Python programming."),
        Message(
            role="assistant",
            content="I'd be happy to help you with Python! What specific topic would you like to learn about?",
        ),
    ]

    messages2 = [
        Message(role="user", content="I want to learn about list comprehensions."),
        Message(
            role="assistant",
            content="List comprehensions are a concise way to create lists in Python. Here's the basic syntax: [expression for item in iterable if condition].",
        ),
    ]

    # Create sample runs
    run1 = RunOutput(run_id="run_1", messages=messages1, status=RunStatus.completed)

    run2 = RunOutput(run_id="run_2", messages=messages2, status=RunStatus.completed)

    # Create agent session
    session = AgentSession(session_id="test_session", agent_id="test_agent", user_id="test_user", runs=[run1, run2])

    return session


def test_get_response_format_native_structured_outputs(session_summary_manager):
    """Test get_response_format with native structured outputs support."""
    # Mock model with native structured outputs
    model = Mock()
    model.supports_native_structured_outputs = True
    model.supports_json_schema_outputs = False

    response_format = session_summary_manager.get_response_format(model)

    assert response_format == SessionSummaryResponse


def test_get_response_format_json_schema_outputs(session_summary_manager):
    """Test get_response_format with JSON schema outputs support."""
    # Mock model with JSON schema outputs
    model = Mock()
    model.supports_native_structured_outputs = False
    model.supports_json_schema_outputs = True

    response_format = session_summary_manager.get_response_format(model)

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == SessionSummaryResponse.__name__


def test_get_response_format_json_object_fallback(session_summary_manager):
    """Test get_response_format with JSON object fallback."""
    # Mock model without structured outputs
    model = Mock()
    model.supports_native_structured_outputs = False
    model.supports_json_schema_outputs = False

    response_format = session_summary_manager.get_response_format(model)

    assert response_format == {"type": "json_object"}


def test_get_system_message_with_custom_prompt(session_summary_manager, mock_agent_session):
    """Test get_system_message with custom session summary prompt."""
    custom_prompt = "Summarize this conversation in a specific way."
    session_summary_manager.session_summary_prompt = custom_prompt

    conversation = mock_agent_session.get_messages()
    response_format = {"type": "json_object"}

    system_message = session_summary_manager.get_system_message(conversation, response_format)

    assert system_message.role == "system"
    assert custom_prompt in system_message.content
    assert "<conversation>" in system_message.content


def test_get_system_message_default_prompt(session_summary_manager, mock_agent_session):
    """Test get_system_message with default prompt generation."""
    conversation = mock_agent_session.get_messages()
    response_format = SessionSummaryResponse

    system_message = session_summary_manager.get_system_message(conversation, response_format)

    assert system_message.role == "system"
    assert "Analyze the following conversation" in system_message.content
    assert "<conversation>" in system_message.content
    assert "User: Hello, I need help with Python programming." in system_message.content
    assert "Assistant: I'd be happy to help you with Python!" in system_message.content


def test_get_system_message_with_json_object_format(session_summary_manager, mock_agent_session):
    """Test get_system_message with JSON object response format."""
    conversation = mock_agent_session.get_messages()
    response_format = {"type": "json_object"}

    with patch("agno.utils.prompts.get_json_output_prompt") as mock_json_prompt:
        mock_json_prompt.return_value = "\nPlease respond with valid JSON."

        system_message = session_summary_manager.get_system_message(conversation, response_format)

        assert "Please respond with valid JSON." in system_message.content
        mock_json_prompt.assert_called_once()


def test_prepare_summary_messages(session_summary_manager, mock_agent_session):
    """Test _prepare_summary_messages method."""
    messages = session_summary_manager._prepare_summary_messages(mock_agent_session)

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[1].content == "Provide the summary of the conversation."


def test_process_summary_response_native_structured(session_summary_manager):
    """Test _process_summary_response with native structured outputs."""
    # Mock response with native structured output
    mock_response = Mock()
    mock_parsed = SessionSummaryResponse(
        summary="Discussion about Python list comprehensions", topics=["Python", "programming", "list comprehensions"]
    )
    mock_response.parsed = mock_parsed

    # Mock model with native structured outputs
    model = Mock()
    model.supports_native_structured_outputs = True

    result = session_summary_manager._process_summary_response(mock_response, model)

    assert isinstance(result, SessionSummary)
    assert result.summary == "Discussion about Python list comprehensions"
    assert result.topics == ["Python", "programming", "list comprehensions"]
    assert result.updated_at is not None


def test_process_summary_response_string_content(session_summary_manager):
    """Test _process_summary_response with string content."""
    # Mock response with string content
    mock_response = Mock()
    mock_response.content = '{"summary": "Python programming help", "topics": ["Python", "programming"]}'
    mock_response.parsed = None

    # Mock model without native structured outputs
    model = Mock()
    model.supports_native_structured_outputs = False

    with patch("agno.utils.string.parse_response_model_str") as mock_parse:
        mock_parse.return_value = SessionSummaryResponse(
            summary="Python programming help", topics=["Python", "programming"]
        )

        result = session_summary_manager._process_summary_response(mock_response, model)

        assert isinstance(result, SessionSummary)
        assert result.summary == "Python programming help"
        assert result.topics == ["Python", "programming"]


def test_process_summary_response_parse_failure(session_summary_manager):
    """Test _process_summary_response with parsing failure."""
    # Mock response with unparseable content
    mock_response = Mock()
    mock_response.content = "invalid json content"
    mock_response.parsed = None

    # Mock model without native structured outputs
    model = Mock()
    model.supports_native_structured_outputs = False

    with patch("agno.utils.string.parse_response_model_str") as mock_parse:
        mock_parse.return_value = None

        result = session_summary_manager._process_summary_response(mock_response, model)

        assert result is None


def test_process_summary_response_none_input(session_summary_manager):
    """Test _process_summary_response with None input."""
    model = Mock()

    result = session_summary_manager._process_summary_response(None, model)

    assert result is None


def test_create_session_summary_success(session_summary_manager, mock_agent_session):
    """Test successful session summary creation."""
    # Mock model response
    mock_response = Mock()
    mock_parsed = SessionSummaryResponse(
        summary="Discussion about Python list comprehensions and programming concepts",
        topics=["Python", "programming", "list comprehensions", "examples"],
    )
    mock_response.parsed = mock_parsed

    # Mock model
    session_summary_manager.model.supports_native_structured_outputs = True

    with patch.object(session_summary_manager.model, "response", return_value=mock_response):
        result = session_summary_manager.create_session_summary(mock_agent_session)

        assert isinstance(result, SessionSummary)
        assert "Python" in result.summary
        assert "programming" in result.summary
        assert len(result.topics) > 0
        assert mock_agent_session.summary == result
        assert session_summary_manager.summaries_updated is True


def test_create_session_summary_no_model(mock_agent_session):
    """Test session summary creation with no model."""
    session_summary_manager = SessionSummaryManager(model=None)

    result = session_summary_manager.create_session_summary(mock_agent_session)

    assert result is None
    assert session_summary_manager.summaries_updated is False


@pytest.mark.asyncio
async def test_acreate_session_summary_success(session_summary_manager, mock_agent_session):
    """Test successful async session summary creation."""
    # Mock model response
    mock_response = Mock()
    mock_parsed = SessionSummaryResponse(
        summary="Async discussion about Python programming",
        topics=["Python", "async programming", "list comprehensions"],
    )
    mock_response.parsed = mock_parsed

    # Mock model
    session_summary_manager.model.supports_native_structured_outputs = True

    with patch.object(session_summary_manager.model, "aresponse", return_value=mock_response):
        result = await session_summary_manager.acreate_session_summary(mock_agent_session)

        assert isinstance(result, SessionSummary)
        assert "Python" in result.summary
        assert "programming" in result.summary
        assert len(result.topics) > 0
        assert mock_agent_session.summary == result
        assert session_summary_manager.summaries_updated is True


@pytest.mark.asyncio
async def test_acreate_session_summary_no_model(mock_agent_session):
    """Test async session summary creation with no model."""
    session_summary_manager = SessionSummaryManager(model=None)

    result = await session_summary_manager.acreate_session_summary(mock_agent_session)

    assert result is None
    assert session_summary_manager.summaries_updated is False


def test_create_session_summary_with_real_session(session_summary_manager, agent_session_with_db):
    """Test session summary creation with a real agent session."""
    # Mock model response for real session
    mock_response = Mock()
    mock_parsed = SessionSummaryResponse(
        summary="User asked for help with Python programming, specifically list comprehensions",
        topics=["Python", "programming", "list comprehensions", "help"],
    )
    mock_response.parsed = mock_parsed

    # Mock model
    session_summary_manager.model.supports_native_structured_outputs = True

    with patch.object(session_summary_manager.model, "response", return_value=mock_response):
        result = session_summary_manager.create_session_summary(agent_session_with_db)

        assert isinstance(result, SessionSummary)
        assert "Python" in result.summary
        assert "programming" in result.summary
        assert len(result.topics) > 0
        assert agent_session_with_db.summary == result


def test_session_summary_to_dict():
    """Test SessionSummary to_dict method."""
    summary = SessionSummary(
        summary="Test summary", topics=["topic1", "topic2"], updated_at=datetime(2023, 1, 1, 12, 0, 0)
    )

    result = summary.to_dict()

    assert result["summary"] == "Test summary"
    assert result["topics"] == ["topic1", "topic2"]
    assert result["updated_at"] == "2023-01-01T12:00:00"


def test_session_summary_from_dict():
    """Test SessionSummary from_dict method."""
    data = {"summary": "Test summary", "topics": ["topic1", "topic2"], "updated_at": "2023-01-01T12:00:00"}

    summary = SessionSummary.from_dict(data)

    assert summary.summary == "Test summary"
    assert summary.topics == ["topic1", "topic2"]
    assert summary.updated_at == datetime(2023, 1, 1, 12, 0, 0)


def test_session_summary_from_dict_no_timestamp():
    """Test SessionSummary from_dict method without timestamp."""
    data = {"summary": "Test summary", "topics": ["topic1", "topic2"]}

    summary = SessionSummary.from_dict(data)

    assert summary.summary == "Test summary"
    assert summary.topics == ["topic1", "topic2"]
    assert summary.updated_at is None


def test_session_summary_response_to_dict():
    """Test SessionSummaryResponse to_dict method."""
    response = SessionSummaryResponse(summary="Test summary", topics=["topic1", "topic2"])

    result = response.to_dict()

    assert result["summary"] == "Test summary"
    assert result["topics"] == ["topic1", "topic2"]


def test_session_summary_response_to_json():
    """Test SessionSummaryResponse to_json method."""
    response = SessionSummaryResponse(summary="Test summary", topics=["topic1", "topic2"])

    result = response.to_json()

    assert '"summary": "Test summary"' in result
    # Fix: Check for individual topic items instead of the whole array
    assert '"topic1"' in result
    assert '"topic2"' in result
    # Or check for the topics key
    assert '"topics":' in result


def test_summaries_updated_flag(session_summary_manager, mock_agent_session):
    """Test that summaries_updated flag is properly set."""
    # Initially should be False
    assert session_summary_manager.summaries_updated is False

    # Mock successful response
    mock_response = Mock()
    mock_parsed = SessionSummaryResponse(summary="Test", topics=["test"])
    mock_response.parsed = mock_parsed

    session_summary_manager.model.supports_native_structured_outputs = True

    with patch.object(session_summary_manager.model, "response", return_value=mock_response):
        # After creating summary, should be True
        session_summary_manager.create_session_summary(mock_agent_session)
        assert session_summary_manager.summaries_updated is True


@pytest.mark.asyncio
async def test_async_summaries_updated_flag(session_summary_manager, mock_agent_session):
    """Test that summaries_updated flag is properly set in async method."""
    # Initially should be False
    assert session_summary_manager.summaries_updated is False

    # Mock successful response
    mock_response = Mock()
    mock_parsed = SessionSummaryResponse(summary="Test", topics=["test"])
    mock_response.parsed = mock_parsed

    session_summary_manager.model.supports_native_structured_outputs = True

    with patch.object(session_summary_manager.model, "aresponse", return_value=mock_response):
        # After creating summary, should be True
        await session_summary_manager.acreate_session_summary(mock_agent_session)
        assert session_summary_manager.summaries_updated is True


def test_summaries_updated_flag_failure_case(session_summary_manager, mock_agent_session):
    """Test that summaries_updated flag is NOT set when summary creation fails."""
    # Initially should be False
    assert session_summary_manager.summaries_updated is False

    # Mock failed response that returns None from _process_summary_response
    mock_response = Mock()
    mock_response.parsed = None
    mock_response.content = "invalid json content"

    session_summary_manager.model.supports_native_structured_outputs = False

    # Mock parse_response_model_str to return None (parsing failure)
    with (
        patch("agno.utils.string.parse_response_model_str") as mock_parse,
        patch.object(session_summary_manager.model, "response", return_value=mock_response),
    ):
        mock_parse.return_value = None

        result = session_summary_manager.create_session_summary(mock_agent_session)

        # Should return None and flag should remain False
        assert result is None
        assert session_summary_manager.summaries_updated is False
        assert mock_agent_session.summary is None


@pytest.mark.asyncio
async def test_async_summaries_updated_flag_failure_case(session_summary_manager, mock_agent_session):
    """Test that summaries_updated flag is NOT set when async summary creation fails."""
    # Initially should be False
    assert session_summary_manager.summaries_updated is False

    # Mock failed response that returns None from _process_summary_response
    mock_response = Mock()
    mock_response.parsed = None
    mock_response.content = "invalid json content"

    session_summary_manager.model.supports_native_structured_outputs = False

    # Mock parse_response_model_str to return None (parsing failure)
    with (
        patch("agno.utils.string.parse_response_model_str") as mock_parse,
        patch.object(session_summary_manager.model, "aresponse", return_value=mock_response),
    ):
        mock_parse.return_value = None

        result = await session_summary_manager.acreate_session_summary(mock_agent_session)

        # Should return None and flag should remain False
        assert result is None
        assert session_summary_manager.summaries_updated is False
        assert mock_agent_session.summary is None


def test_summaries_updated_flag_none_response(session_summary_manager, mock_agent_session):
    """Test that summaries_updated flag is NOT set when model returns None response."""
    # Initially should be False
    assert session_summary_manager.summaries_updated is False

    with patch.object(session_summary_manager.model, "response", return_value=None):
        result = session_summary_manager.create_session_summary(mock_agent_session)

        # Should return None and flag should remain False
        assert result is None
        assert session_summary_manager.summaries_updated is False
        assert mock_agent_session.summary is None


# ---------------------------------------------------------------------------
# Tests for last_n_runs and conversation_limit parameters
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_run_agent_session():
    """Create an agent session with multiple runs for testing last_n_runs and conversation_limit."""
    from agno.run.base import RunStatus

    runs = []
    for i in range(5):
        messages = [
            Message(role="user", content=f"User message from run {i + 1}"),
            Message(role="assistant", content=f"Assistant response from run {i + 1}"),
        ]
        runs.append(RunOutput(run_id=f"run_{i + 1}", messages=messages, status=RunStatus.completed))

    session = AgentSession(
        session_id="test_multi_run_session",
        agent_id="test_agent",
        user_id="test_user",
        runs=runs,
    )
    return session


def test_last_n_runs_default_none(model):
    """Test that last_n_runs defaults to None (all runs)."""
    manager = SessionSummaryManager(model=model)
    assert manager.last_n_runs is None


def test_conversation_limit_default_none(model):
    """Test that conversation_limit defaults to None (no limit)."""
    manager = SessionSummaryManager(model=model)
    assert manager.conversation_limit is None


def test_prepare_summary_messages_with_last_n_runs(model, multi_run_agent_session):
    """Test that last_n_runs limits which runs are included in summary messages."""
    manager = SessionSummaryManager(model=model, last_n_runs=2)

    messages = manager._prepare_summary_messages(multi_run_agent_session)

    assert messages is not None
    system_message = messages[0]
    # Should only contain messages from the last 2 runs (run 4 and run 5)
    assert "run 4" in system_message.content
    assert "run 5" in system_message.content
    # Should NOT contain messages from earlier runs
    assert "run 1" not in system_message.content
    assert "run 2" not in system_message.content
    assert "run 3" not in system_message.content


def test_prepare_summary_messages_with_conversation_limit(model, multi_run_agent_session):
    """Test that conversation_limit caps the number of messages in the summary."""
    manager = SessionSummaryManager(model=model, conversation_limit=4)

    messages = manager._prepare_summary_messages(multi_run_agent_session)

    assert messages is not None
    system_message = messages[0]
    # With limit=4, should only have the last 4 messages (from runs 4 and 5)
    assert "run 5" in system_message.content
    assert "run 4" in system_message.content
    # Earlier runs should be excluded
    assert "run 1" not in system_message.content
    assert "run 2" not in system_message.content


def test_prepare_summary_messages_all_runs(model, multi_run_agent_session):
    """Test that without last_n_runs or conversation_limit, all runs are included."""
    manager = SessionSummaryManager(model=model)

    messages = manager._prepare_summary_messages(multi_run_agent_session)

    assert messages is not None
    system_message = messages[0]
    # All 5 runs should be present
    for i in range(1, 6):
        assert f"run {i}" in system_message.content


def test_create_session_summary_with_last_n_runs(model, multi_run_agent_session):
    """Test that create_session_summary respects last_n_runs."""
    manager = SessionSummaryManager(model=model, last_n_runs=1)

    mock_response = Mock()
    mock_response.parsed = SessionSummaryResponse(summary="Summary of last run", topics=["test"])

    manager.model.supports_native_structured_outputs = True

    with patch.object(manager.model, "response", return_value=mock_response) as mock_model_response:
        result = manager.create_session_summary(multi_run_agent_session)

        assert isinstance(result, SessionSummary)
        # Verify the model was called - the filtering happened in get_messages
        mock_model_response.assert_called_once()
        # Check that the system message only contains the last run
        call_args = mock_model_response.call_args
        system_msg = call_args.kwargs["messages"][0].content
        assert "run 5" in system_msg
        assert "run 1" not in system_msg


def test_prepare_summary_messages_with_both_last_n_runs_and_conversation_limit(model, multi_run_agent_session):
    """Test that last_n_runs and conversation_limit compose correctly when both are set."""
    # last_n_runs=3 limits to runs 3, 4, 5 (6 messages)
    # conversation_limit=2 then takes only the last 2 of those messages
    manager = SessionSummaryManager(model=model, last_n_runs=3, conversation_limit=2)

    messages = manager._prepare_summary_messages(multi_run_agent_session)

    assert messages is not None
    system_message = messages[0]
    # Should contain only the last 2 messages from the last 3 runs
    # The last 2 messages are from run 5
    assert "run 5" in system_message.content
    # Earlier runs should be excluded by the combination of both filters
    assert "run 1" not in system_message.content
    assert "run 2" not in system_message.content


def test_get_messages_composes_last_n_runs_and_limit(multi_run_agent_session):
    """Test that get_messages applies last_n_runs before limit at the session level."""
    # last_n_runs=2 limits to runs 4 and 5 (4 messages)
    # limit=3 then takes the last 3 of those 4 messages
    messages = multi_run_agent_session.get_messages(last_n_runs=2, limit=3)

    # Should have 3 messages from runs 4 and 5
    assert len(messages) == 3
    contents = [m.content for m in messages]
    # All messages should be from runs 4 and 5
    for content in contents:
        assert "run 1" not in content
        assert "run 2" not in content
        assert "run 3" not in content


@pytest.mark.asyncio
async def test_acreate_session_summary_with_last_n_runs(model, multi_run_agent_session):
    """Test that acreate_session_summary respects last_n_runs."""
    manager = SessionSummaryManager(model=model, last_n_runs=1)

    mock_response = Mock()
    mock_response.parsed = SessionSummaryResponse(summary="Summary of last run", topics=["test"])

    manager.model.supports_native_structured_outputs = True

    with patch.object(manager.model, "aresponse", return_value=mock_response) as mock_model_response:
        result = await manager.acreate_session_summary(multi_run_agent_session)

        assert isinstance(result, SessionSummary)
        mock_model_response.assert_called_once()
        call_args = mock_model_response.call_args
        system_msg = call_args.kwargs["messages"][0].content
        assert "run 5" in system_msg
        assert "run 1" not in system_msg


# ---------------------------------------------------------------------------
# Tests for TeamSession get_messages with last_n_runs and limit
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_run_team_session():
    """Create a team session with multiple runs for testing last_n_runs and conversation_limit."""
    from agno.run.base import RunStatus

    runs = []
    for i in range(5):
        messages = [
            Message(role="user", content=f"User message from run {i + 1}"),
            Message(role="assistant", content=f"Assistant response from run {i + 1}"),
        ]
        runs.append(
            TeamRunOutput(
                team_id="test_team",
                run_id=f"run_{i + 1}",
                messages=messages,
                status=RunStatus.completed,
            )
        )

    session = TeamSession(
        session_id="test_multi_run_team_session",
        team_id="test_team",
        runs=runs,
    )
    return session


def test_team_get_messages_with_last_n_runs(multi_run_team_session):
    """Test that TeamSession.get_messages respects last_n_runs."""
    messages = multi_run_team_session.get_messages(last_n_runs=2)

    contents = [m.content for m in messages]
    # Should only have messages from runs 4 and 5
    assert any("run 4" in c for c in contents)
    assert any("run 5" in c for c in contents)
    assert not any("run 1" in c for c in contents)
    assert not any("run 2" in c for c in contents)
    assert not any("run 3" in c for c in contents)


def test_team_get_messages_with_limit(multi_run_team_session):
    """Test that TeamSession.get_messages respects limit."""
    messages = multi_run_team_session.get_messages(limit=4)

    assert len(messages) == 4
    contents = [m.content for m in messages]
    # Should have the last 4 messages (from runs 4 and 5)
    assert any("run 5" in c for c in contents)
    assert any("run 4" in c for c in contents)
    assert not any("run 1" in c for c in contents)


def test_team_get_messages_composes_last_n_runs_and_limit(multi_run_team_session):
    """Test that TeamSession.get_messages applies last_n_runs before limit."""
    # last_n_runs=2 limits to runs 4 and 5 (4 messages)
    # limit=3 then takes the last 3 of those 4 messages
    messages = multi_run_team_session.get_messages(last_n_runs=2, limit=3)

    assert len(messages) == 3
    contents = [m.content for m in messages]
    for content in contents:
        assert "run 1" not in content
        assert "run 2" not in content
        assert "run 3" not in content


def test_team_get_messages_all_runs(multi_run_team_session):
    """Test that TeamSession.get_messages returns all runs when no limits set."""
    messages = multi_run_team_session.get_messages()

    contents = [m.content for m in messages]
    for i in range(1, 6):
        assert any(f"run {i}" in c for c in contents)


# ---------------------------------------------------------------------------
# Boundary value tests for last_n_runs and limit
# ---------------------------------------------------------------------------


def test_agent_get_messages_last_n_runs_zero(multi_run_agent_session):
    """Test that last_n_runs=0 returns an empty list."""
    messages = multi_run_agent_session.get_messages(last_n_runs=0)
    assert messages == []


def test_agent_get_messages_limit_zero(multi_run_agent_session):
    """Test that limit=0 returns an empty list."""
    messages = multi_run_agent_session.get_messages(limit=0)
    assert messages == []


def test_team_get_messages_last_n_runs_zero(multi_run_team_session):
    """Test that last_n_runs=0 returns an empty list for team sessions."""
    messages = multi_run_team_session.get_messages(last_n_runs=0)
    assert messages == []


def test_team_get_messages_limit_zero(multi_run_team_session):
    """Test that limit=0 returns an empty list for team sessions."""
    messages = multi_run_team_session.get_messages(limit=0)
    assert messages == []


def test_session_summary_manager_rejects_negative_last_n_runs(model):
    """Test that SessionSummaryManager raises ValueError for negative last_n_runs."""
    with pytest.raises(ValueError, match="last_n_runs must be a positive integer"):
        SessionSummaryManager(model=model, last_n_runs=-1)


def test_session_summary_manager_rejects_zero_last_n_runs(model):
    """Test that SessionSummaryManager raises ValueError for zero last_n_runs."""
    with pytest.raises(ValueError, match="last_n_runs must be a positive integer"):
        SessionSummaryManager(model=model, last_n_runs=0)


def test_session_summary_manager_rejects_negative_conversation_limit(model):
    """Test that SessionSummaryManager raises ValueError for negative conversation_limit."""
    with pytest.raises(ValueError, match="conversation_limit must be a positive integer"):
        SessionSummaryManager(model=model, conversation_limit=-1)


def test_session_summary_manager_rejects_zero_conversation_limit(model):
    """Test that SessionSummaryManager raises ValueError for zero conversation_limit."""
    with pytest.raises(ValueError, match="conversation_limit must be a positive integer"):
        SessionSummaryManager(model=model, conversation_limit=0)
