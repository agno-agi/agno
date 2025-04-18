from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.memory.v2 import MemoryManager, SessionSummarizer
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.memory import Memory
from agno.memory.v2.schema import SessionSummary, UserMemory
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.run.response import RunResponse


@pytest.fixture
def mock_model():
    model = Mock()
    model.supports_native_structured_outputs = False
    model.supports_json_schema_outputs = False
    model.response_format = {"type": "json_object"}
    return model


@pytest.fixture
def memory_with_model(mock_model):
    return Memory(model=mock_model)


@pytest.fixture
def mock_memory_manager():
    manager = Mock()
    return manager


@pytest.fixture
def mock_summary_manager():
    manager = Mock()
    return manager


@pytest.fixture
def mock_db():
    db = Mock()
    db.read_memories.return_value = []
    return db


@pytest.fixture
def memory_with_managers(mock_model, mock_db, mock_memory_manager, mock_summary_manager):
    return Memory(model=mock_model, db=mock_db, memory_manager=mock_memory_manager, summarizer=mock_summary_manager)


@pytest.fixture
def sample_user_memory():
    return UserMemory(memory="The user's name is John Doe", topics=["name", "user"], last_updated=datetime.now())


@pytest.fixture
def sample_session_summary():
    return SessionSummary(
        summary="This was a session about stocks", topics=["stocks", "finance"], last_updated=datetime.now()
    )


@pytest.fixture
def sample_run_response():
    return RunResponse(
        content="Sample response content",
        messages=[Message(role="user", content="Hello"), Message(role="assistant", content="Hi there!")],
    )


# Memory Initialization Tests
def test_default_initialization():
    memory = Memory()
    assert memory.memories == {}
    assert memory.summaries == {}
    assert memory.runs == {}
    assert memory.model is None


def test_initialization_with_model():
    model = OpenAIChat()
    memory = Memory(model=model)
    assert memory.model == model
    assert memory.memory_manager is not None
    assert memory.memory_manager.model == model


def test_set_model():
    model = OpenAIChat()
    memory = Memory(memory_manager=MemoryManager())
    memory.set_model(model)
    assert memory.memory_manager is not None
    assert memory.memory_manager.model == model
    assert memory.summary_manager is not None
    assert memory.summary_manager.model == model


def test_custom_memory_manager_with_system_message(mock_model, mock_db):
    # Create a custom system prompt
    custom_system_message = "You are a specialized memory manager that focuses on capturing user preferences."

    # Create a memory manager with the custom system prompt
    memory_manager = MemoryManager(model=mock_model, system_message=custom_system_message)

    # Create a memory with the custom memory manager
    memory = Memory(model=mock_model, db=mock_db, memory_manager=memory_manager)

    # Test that the get_system_message method returns the custom prompt
    system_message = memory.memory_manager.get_system_message()
    assert system_message.role == "system"
    assert system_message.content == custom_system_message

    # Test that the custom prompt is used when creating memories
    with patch.object(memory.memory_manager, "create_or_update_memories") as mock_create:
        mock_create.return_value = "Memories created with custom message"

        # Call the method that would use the system prompt
        result = memory.create_user_memories(message="I like pizza", user_id="test_user")

        # Verify the create_or_update_memories method was called
        mock_create.assert_called_once()

        # Verify the result
        assert result == "Memories created with custom message"


def test_custom_memory_manager_with_additional_instructions(mock_model, mock_db):
    # Create a custom system prompt
    custom_additional_instructions = "Don't store any memories about the user's name."

    # Create a memory manager with the custom system prompt
    memory_manager = MemoryManager(model=mock_model, additional_instructions=custom_additional_instructions)

    # Create a memory with the custom memory manager
    memory = Memory(model=mock_model, db=mock_db, memory_manager=memory_manager)

    # Test that the get_system_message method returns the custom prompt
    system_message = memory.memory_manager.get_system_message()
    assert system_message.role == "system"
    assert custom_additional_instructions in system_message.content


def test_custom_summarizer_with_system_message(mock_model, mock_db):
    # Create a custom system prompt for the summarizer
    custom_system_message = (
        "You are a specialized summarizer that focuses on extracting key action items from conversations."
    )

    # Create a summarizer with the custom system prompt
    summarizer = SessionSummarizer(model=mock_model, system_message=custom_system_message)

    # Create a memory with the custom summarizer
    memory = Memory(model=mock_model, db=mock_db, summarizer=summarizer)

    # Verify the summarizer has the custom system prompt
    assert memory.summary_manager.system_message == custom_system_message

    # Test that the get_system_message method returns the custom prompt
    # Create a sample conversation for testing
    conversation = [
        Message(role="user", content="I need to schedule a meeting for next week"),
        Message(role="assistant", content="I can help with that. What day works best for you?"),
        Message(role="user", content="Tuesday afternoon would be good"),
    ]

    # Get the system message with the custom prompt
    system_message = memory.summary_manager.get_system_message(conversation, model=mock_model)
    assert system_message.role == "system"
    assert system_message.content == custom_system_message

    # Test that the custom prompt is used when creating session summaries
    with patch.object(memory.summary_manager, "run") as mock_run:
        # Create a mock SessionSummaryResponse
        mock_summary_response = MagicMock()
        mock_summary_response.summary = "Meeting scheduled for Tuesday afternoon"
        mock_summary_response.topics = ["scheduling", "meeting"]
        mock_run.return_value = mock_summary_response

        # Add a run to have messages for the summary
        session_id = "test_session"
        user_id = "test_user"

        run_response = RunResponse(
            content="Sample response",
            messages=[
                Message(role="user", content="I need to schedule a meeting for next week"),
                Message(role="assistant", content="I can help with that. What day works best for you?"),
                Message(role="user", content="Tuesday afternoon would be good"),
                Message(role="assistant", content="I'll schedule that for you."),
            ],
        )

        memory.add_run(session_id, run_response)

        # Create the summary
        summary = memory.create_session_summary(session_id, user_id)

        # Verify the run method was called
        mock_run.assert_called_once()

        # Verify the summary was created with the custom prompt
        assert summary is not None
        assert summary.summary == "Meeting scheduled for Tuesday afternoon"
        assert summary.topics == ["scheduling", "meeting"]
        assert memory.summaries[user_id][session_id] == summary


def test_custom_summarizer_with_additional_instructions(mock_model, mock_db):
    # Create a custom system prompt
    custom_additional_instructions = "Don't include any memories in the summary."

    # Create a summarizer with the custom system prompt
    summarizer = SessionSummarizer(model=mock_model, additional_instructions=custom_additional_instructions)

    # Create a memory with the custom summarizer
    memory = Memory(model=mock_model, db=mock_db, summarizer=summarizer)

    # Test that the get_system_message method returns the custom prompt
    # Create a sample conversation for testing
    conversation = [
        Message(role="user", content="I need to schedule a meeting for next week"),
        Message(role="assistant", content="I can help with that. What day works best for you?"),
        Message(role="user", content="Tuesday afternoon would be good"),
    ]

    # Get the system message with the custom prompt
    system_message = memory.summary_manager.get_system_message(conversation, model=mock_model)
    assert system_message.role == "system"
    assert custom_additional_instructions in system_message.content


# User Memory Operations Tests
def test_add_user_memory(memory_with_model, sample_user_memory):
    memory_id = memory_with_model.add_user_memory(memory=sample_user_memory, user_id="test_user")

    assert memory_id is not None
    assert memory_with_model.memories["test_user"][memory_id] == sample_user_memory
    assert memory_with_model.get_user_memory(user_id="test_user", memory_id=memory_id) == sample_user_memory


def test_add_user_memory_default_user(memory_with_model, sample_user_memory):
    memory_id = memory_with_model.add_user_memory(memory=sample_user_memory)

    assert memory_id is not None
    assert memory_with_model.memories["default"][memory_id] == sample_user_memory
    assert memory_with_model.get_user_memory(user_id="default", memory_id=memory_id) == sample_user_memory


def test_replace_user_memory(memory_with_model, sample_user_memory):
    # First add a memory
    memory_id = memory_with_model.add_user_memory(memory=sample_user_memory, user_id="test_user")

    # Now replace it
    updated_memory = UserMemory(
        memory="The user's name is Jane Doe", topics=["name", "user"], last_updated=datetime.now()
    )

    memory_with_model.replace_user_memory(memory_id=memory_id, memory=updated_memory, user_id="test_user")

    retrieved_memory = memory_with_model.get_user_memory(user_id="test_user", memory_id=memory_id)
    assert retrieved_memory == updated_memory
    assert retrieved_memory.memory == "The user's name is Jane Doe"


def test_delete_user_memory(memory_with_model, sample_user_memory):
    # First add a memory
    memory_id = memory_with_model.add_user_memory(memory=sample_user_memory, user_id="test_user")

    # Verify it exists
    assert memory_with_model.get_user_memory(user_id="test_user", memory_id=memory_id) is not None

    # Now delete it
    memory_with_model.delete_user_memory(user_id="test_user", memory_id=memory_id)

    # Verify it's gone
    assert memory_id not in memory_with_model.memories["test_user"]


def test_get_user_memories(memory_with_model, sample_user_memory):
    # Add two memories
    memory_with_model.add_user_memory(memory=sample_user_memory, user_id="test_user")

    memory_with_model.add_user_memory(
        memory=UserMemory(memory="User likes pizza", topics=["food"]), user_id="test_user"
    )

    # Get all memories for the user
    memories = memory_with_model.get_user_memories(user_id="test_user")

    assert len(memories) == 2
    assert any(m.memory == "The user's name is John Doe" for m in memories)
    assert any(m.memory == "User likes pizza" for m in memories)


# Session Summary Operations Tests
def test_create_session_summary(memory_with_managers):
    # Setup the mock to return a summary
    mock_summary = MagicMock()
    mock_summary.summary = "Test summary"
    mock_summary.topics = ["test"]
    memory_with_managers.summary_manager.run.return_value = mock_summary

    # Add a run to have messages for the summary
    session_id = "test_session"
    user_id = "test_user"

    run_response = RunResponse(
        content="Sample response",
        messages=[Message(role="user", content="Hello"), Message(role="assistant", content="Hi there!")],
    )

    memory_with_managers.add_run(session_id, run_response)

    # Create the summary
    summary = memory_with_managers.create_session_summary(session_id, user_id)

    assert summary is not None
    assert summary.summary == "Test summary"
    assert summary.topics == ["test"]
    assert memory_with_managers.summaries[user_id][session_id] == summary


def test_get_session_summary(memory_with_model, sample_session_summary):
    # Add a summary
    session_id = "test_session"
    user_id = "test_user"

    memory_with_model.summaries = {user_id: {session_id: sample_session_summary}}

    # Retrieve the summary
    summary = memory_with_model.get_session_summary(user_id=user_id, session_id=session_id)

    assert summary == sample_session_summary
    assert summary.summary == "This was a session about stocks"


def test_delete_session_summary(memory_with_model, sample_session_summary):
    # Add a summary
    session_id = "test_session"
    user_id = "test_user"

    memory_with_model.summaries = {user_id: {session_id: sample_session_summary}}

    # Verify it exists
    assert memory_with_model.get_session_summary(user_id=user_id, session_id=session_id) is not None

    # Now delete it
    memory_with_model.delete_session_summary(user_id, session_id)

    # Verify it's gone
    assert session_id not in memory_with_model.summaries[user_id]


# Memory Search Tests
def test_search_user_memories_agentic(memory_with_model):
    # Setup test data
    memory_with_model.memories = {
        "test_user": {
            "memory1": UserMemory(memory="Memory 1", topics=["topic1"]),
            "memory2": UserMemory(memory="Memory 2", topics=["topic2"]),
        }
    }

    # Mock the internal method
    with patch.object(memory_with_model, "_search_user_memories_agentic") as mock_search:
        # Setup the mock to return a memory list
        mock_memories = [
            UserMemory(memory="Memory 1", topics=["topic1"]),
            UserMemory(memory="Memory 2", topics=["topic2"]),
        ]
        mock_search.return_value = mock_memories

        # Call the search function
        results = memory_with_model.search_user_memories(
            query="test query", retrieval_method="agentic", user_id="test_user"
        )

        # Verify the search was called correctly
        mock_search.assert_called_once_with(user_id="test_user", query="test query", limit=None)
        assert results == mock_memories


def test_search_user_memories_last_n(memory_with_model):
    # Setup test data
    memory_with_model.memories = {
        "test_user": {
            "memory1": UserMemory(memory="Memory 1", topics=["topic1"]),
            "memory2": UserMemory(memory="Memory 2", topics=["topic2"]),
        }
    }

    # Mock the internal method
    with patch.object(memory_with_model, "_get_last_n_memories") as mock_search:
        # Setup the mock to return a memory list
        mock_memories = [
            UserMemory(memory="Recent Memory 1", topics=["topic1"]),
            UserMemory(memory="Recent Memory 2", topics=["topic2"]),
        ]
        mock_search.return_value = mock_memories

        # Call the search function
        results = memory_with_model.search_user_memories(retrieval_method="last_n", limit=2, user_id="test_user")

        # Verify the search was called correctly
        mock_search.assert_called_once_with(user_id="test_user", limit=2)
        assert results == mock_memories


def test_search_user_memories_first_n(memory_with_model):
    # Setup test data
    memory_with_model.memories = {
        "test_user": {
            "memory1": UserMemory(memory="Memory 1", topics=["topic1"]),
            "memory2": UserMemory(memory="Memory 2", topics=["topic2"]),
        }
    }

    # Mock the internal method
    with patch.object(memory_with_model, "_get_first_n_memories") as mock_search:
        # Setup the mock to return a memory list
        mock_memories = [
            UserMemory(memory="Old Memory 1", topics=["topic1"]),
            UserMemory(memory="Old Memory 2", topics=["topic2"]),
        ]
        mock_search.return_value = mock_memories

        # Call the search function
        results = memory_with_model.search_user_memories(retrieval_method="first_n", limit=2, user_id="test_user")

        # Verify the search was called correctly
        mock_search.assert_called_once_with(user_id="test_user", limit=2)
        assert results == mock_memories


# Run and Messages Tests
def test_add_run(memory_with_model, sample_run_response):
    session_id = "test_session"

    # Add a run
    memory_with_model.add_run(session_id, sample_run_response)

    # Verify it was added
    assert session_id in memory_with_model.runs
    assert len(memory_with_model.runs[session_id]) == 1
    assert memory_with_model.runs[session_id][0] == sample_run_response


def test_get_messages_for_session(memory_with_model):
    """Test retrieving messages for a session."""
    # Add a run with messages
    session_id = "test_session"

    run_response = RunResponse(
        content="Sample response",
        messages=[
            Message(role="user", content="Hello, how are you?"),
            Message(role="assistant", content="I'm doing well, thank you for asking!"),
        ],
    )

    memory_with_model.add_run(session_id, run_response)

    # Get messages for the session
    messages = memory_with_model.get_messages_for_session(session_id)

    # Verify the messages were retrieved correctly
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello, how are you?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "I'm doing well, thank you for asking!"


def test_get_messages_for_session_with_multiple_runs(memory_with_model):
    """Test retrieving messages for a session with multiple runs."""
    # Add multiple runs with messages
    session_id = "test_session"

    run1 = RunResponse(
        content="First response",
        messages=[
            Message(role="user", content="What's the weather like?"),
            Message(role="assistant", content="It's sunny today."),
        ],
    )

    run2 = RunResponse(
        content="Second response",
        messages=[
            Message(role="user", content="What about tomorrow?"),
            Message(role="assistant", content="It's expected to rain."),
        ],
    )

    memory_with_model.add_run(session_id, run1)
    memory_with_model.add_run(session_id, run2)

    # Get messages for the session
    messages = memory_with_model.get_messages_for_session(session_id)

    # Verify the messages were retrieved correctly
    assert len(messages) == 4
    assert messages[0].role == "user"
    assert messages[0].content == "What's the weather like?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "It's sunny today."
    assert messages[2].role == "user"
    assert messages[2].content == "What about tomorrow?"
    assert messages[3].role == "assistant"
    assert messages[3].content == "It's expected to rain."


def test_get_messages_for_session_with_history_messages(memory_with_model):
    """Test retrieving messages for a session with history messages."""
    # Add a run with history messages
    session_id = "test_session"

    run_response_1 = RunResponse(
        content="Sample response",
        messages=[
            Message(role="user", content="Hello, how are you?", from_history=True),
            Message(role="assistant", content="I'm doing well, thank you for asking!", from_history=True),
        ],
    )

    # The most recent run response
    run_response_2 = RunResponse(
        content="Sample response",
        messages=[
            Message(role="user", content="What's new?"),
            Message(role="assistant", content="Not much, just working on some code."),
        ],
    )

    memory_with_model.add_run(session_id, run_response_1)
    memory_with_model.add_run(session_id, run_response_2)

    # Get messages for the session with skip_history_messages=True (default)
    messages = memory_with_model.get_messages_for_session(session_id)

    # Verify only non-history messages were retrieved
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "What's new?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Not much, just working on some code."

    # Get messages for the session with skip_history_messages=False
    messages = memory_with_model.get_messages_for_session(session_id, skip_history_messages=False)

    # Verify all messages were retrieved
    assert len(messages) == 4
    assert messages[0].role == "user"
    assert messages[0].content == "Hello, how are you?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "I'm doing well, thank you for asking!"
    assert messages[2].role == "user"
    assert messages[2].content == "What's new?"
    assert messages[3].role == "assistant"
    assert messages[3].content == "Not much, just working on some code."


def test_get_messages_from_last_n_runs(memory_with_model):
    """Test retrieving messages from the last N runs."""
    # Add multiple runs with messages
    session_id = "test_session"

    run1 = RunResponse(
        content="First response",
        messages=[
            Message(role="user", content="What's the weather like?"),
            Message(role="assistant", content="It's sunny today."),
        ],
    )

    run2 = RunResponse(
        content="Second response",
        messages=[
            Message(role="user", content="What about tomorrow?"),
            Message(role="assistant", content="It's expected to rain."),
        ],
    )

    memory_with_model.add_run(session_id, run1)
    memory_with_model.add_run(session_id, run2)

    # Get messages from the last 1 run
    messages = memory_with_model.get_messages_from_last_n_runs(session_id, last_n=1)

    # Verify only the last run's messages were retrieved
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "What about tomorrow?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "It's expected to rain."


# Team Context Tests
def test_add_interaction_to_team_context(memory_with_model):
    """Test adding an interaction to team context."""
    # Add a run with messages
    session_id = "test_session"
    member_name = "Researcher"
    task = "Research the latest AI developments"

    run_response = RunResponse(
        content="Research findings",
        messages=[Message(role="assistant", content="I found that the latest AI models have improved significantly.")],
    )

    # Add the interaction to team context
    memory_with_model.add_interaction_to_team_context(session_id, member_name, task, run_response)

    # Verify the interaction was added
    assert session_id in memory_with_model.team_context
    assert len(memory_with_model.team_context[session_id].member_interactions) == 1
    assert memory_with_model.team_context[session_id].member_interactions[0].member_name == member_name
    assert memory_with_model.team_context[session_id].member_interactions[0].task == task
    assert memory_with_model.team_context[session_id].member_interactions[0].response == run_response


def test_set_team_context_text(memory_with_model):
    """Test setting team context text."""
    # Set team context text
    session_id = "test_session"
    context_text = "This is a team working on an AI project"

    memory_with_model.set_team_context_text(session_id, context_text)

    # Verify the team context text was set
    assert session_id in memory_with_model.team_context
    assert memory_with_model.team_context[session_id].text == context_text


def test_get_team_context_str(memory_with_model):
    """Test getting team context as a string."""
    # Set team context text
    session_id = "test_session"
    context_text = "This is a team working on an AI project"

    memory_with_model.set_team_context_text(session_id, context_text)

    # Get team context as a string
    context_str = memory_with_model.get_team_context_str(session_id)

    # Verify the team context string was formatted correctly
    assert "<team context>" in context_str
    assert context_text in context_str
    assert "</team context>" in context_str


def test_get_team_member_interactions_str(memory_with_model):
    """Test getting team member interactions as a string."""
    # Add interactions to team context
    session_id = "test_session"

    run1 = RunResponse(
        content="Research findings",
        messages=[Message(role="assistant", content="I found that the latest AI models have improved significantly.")],
    )

    run2 = RunResponse(
        content="Analysis results",
        messages=[
            Message(role="assistant", content="Based on the research, we should focus on transformer architectures.")
        ],
    )

    memory_with_model.add_interaction_to_team_context(session_id, "Researcher", "Research AI developments", run1)
    memory_with_model.add_interaction_to_team_context(session_id, "Analyst", "Analyze research findings", run2)

    # Get team member interactions as a string
    interactions_str = memory_with_model.get_team_member_interactions_str(session_id)

    # Verify the team member interactions string was formatted correctly
    assert "<member interactions>" in interactions_str
    assert "Researcher" in interactions_str
    assert "Research AI developments" in interactions_str
    assert "Analyst" in interactions_str
    assert "Analyze research findings" in interactions_str
    assert "</member interactions>" in interactions_str


# Memory Integration Tests
def test_create_user_memories(memory_with_managers, mock_db):
    # Setup mock response
    mock_updates = [
        MagicMock(id=None, memory="New memory 1", topics=["topic1"]),
        MagicMock(id=None, memory="New memory 2", topics=["topic2"]),
    ]
    memory_with_managers.memory_manager.create_or_update_memories.return_value = MagicMock(updates=mock_updates)
    mock_db.read_memories.return_value = [
        MemoryRow(user_id="test_user", memory={"memory": "New memory 1", "topics": ["topic1"]}),
        MemoryRow(user_id="test_user", memory={"memory": "New memory 2", "topics": ["topic2"]}),
    ]

    # Create user memories
    messages = [Message(role="user", content="Remember this information")]
    memory_with_managers.create_user_memories(messages=messages, user_id="test_user")

    # Verify memories were created
    assert "test_user" in memory_with_managers.memories
    assert len(memory_with_managers.memories["test_user"]) == 2

    memories = memory_with_managers.get_user_memories("test_user")
    assert any(m.memory == "New memory 1" for m in memories)
    assert any(m.memory == "New memory 2" for m in memories)


def test_to_dict_and_from_dict(memory_with_model, sample_user_memory, sample_session_summary):
    # Setup memory with user memories and summaries
    user_id = "test_user"
    memory_id = memory_with_model.add_user_memory(sample_user_memory, user_id=user_id)

    session_id = "test_session"
    memory_with_model.summaries = {user_id: {session_id: sample_session_summary}}

    # Get dictionary representation
    memory_dict = memory_with_model.to_dict()

    # Verify the dictionary contains our data
    assert "memories" in memory_dict
    assert "summaries" in memory_dict
    assert user_id in memory_dict["memories"]
    assert user_id in memory_dict["summaries"]
    assert session_id in memory_dict["summaries"][user_id]

    # Create a new memory from the dictionary
    new_memory = Memory()
    new_memory.memories = {
        user_id: {
            memory_id: UserMemory.from_dict(memory)
            for memory_id, memory in memory_dict.get("memories", {}).get(user_id, {}).items()
        }
    }
    new_memory.summaries = {
        user_id: {
            session_id: SessionSummary.from_dict(summary)
            for session_id, summary in memory_dict.get("summaries", {}).get(user_id, {}).items()
        }
    }

    # Verify the new memory has the same data
    assert memory_id in new_memory.memories[user_id]
    assert new_memory.memories[user_id][memory_id].memory == sample_user_memory.memory
    assert new_memory.summaries[user_id][session_id].summary == sample_session_summary.summary


def test_clear(memory_with_model, sample_user_memory):
    # Add data to memory
    memory_with_model.add_user_memory(sample_user_memory, user_id="test_user")
    memory_with_model.summaries = {"test_user": {"test_session": SessionSummary(summary="Test summary")}}

    # Clear memory
    memory_with_model.clear()

    # Verify data is cleared
    assert memory_with_model.memories == {}
    assert memory_with_model.summaries == {}
