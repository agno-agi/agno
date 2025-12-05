import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.agent import Message, RunOutput
from agno.session.agent import AgentSession
from agno.session.summary import SessionSummary, SessionSummaryManager, SessionSummaryResponse


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
