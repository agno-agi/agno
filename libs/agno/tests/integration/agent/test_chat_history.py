import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat


@pytest.fixture
def chat_agent(shared_db):
    """Create an agent with storage and memory for testing."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
    )


@pytest.fixture
def memory_agent(shared_db):
    """Create an agent that creates memories."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        update_memory_on_run=True,
    )


def test_agent_runs_in_memory(chat_agent):
    session_id = "test_session"
    response = chat_agent.run("Hello, how are you?", session_id=session_id)
    assert response is not None
    assert response.content is not None
    assert response.run_id is not None

    session_from_db = chat_agent.get_session(session_id=session_id)
    assert session_from_db is not None
    assert len(session_from_db.runs) == 1
    stored_run_response = session_from_db.runs[0]
    assert stored_run_response.run_id == response.run_id
    assert len(stored_run_response.messages) == 2


@pytest.mark.asyncio
async def test_multi_user_multi_session_chat(memory_agent, shared_db):
    """Test multi-user multi-session chat with storage and memory."""
    # Define user and session IDs
    user_1_id = "user_1@example.com"
    user_2_id = "user_2@example.com"

    user_1_session_1_id = "user_1_session_1"
    user_1_session_2_id = "user_1_session_2"
    user_2_session_1_id = "user_2_session_1"

    # Chat with user 1 - Session 1
    await memory_agent.arun(
        "Remember that my name is Mark Gonzales",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )
    await memory_agent.arun(
        "Remember that I enjoy reading manga.",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    # Chat with user 1 - Session 2
    await memory_agent.arun("I'm going to the movies tonight.", user_id=user_1_id, session_id=user_1_session_2_id)

    # Chat with user 2
    await memory_agent.arun("Hi my name is John Doe.", user_id=user_2_id, session_id=user_2_session_1_id)
    await memory_agent.arun(
        "I love hiking and go hiking every weekend.", user_id=user_2_id, session_id=user_2_session_1_id
    )
    # Continue the conversation with user 1
    await memory_agent.arun("What do you suggest I do this weekend?", user_id=user_1_id, session_id=user_1_session_1_id)

    # Verify storage DB has the right sessions
    all_session_ids = shared_db.get_sessions(session_type=SessionType.AGENT)
    assert len(all_session_ids) == 3  # 3 sessions total

    # Check that each user has the expected sessions
    user_1_sessions = shared_db.get_sessions(session_type=SessionType.AGENT, user_id=user_1_id)
    assert len(user_1_sessions) == 2
    assert user_1_session_1_id in [session.session_id for session in user_1_sessions]
    assert user_1_session_2_id in [session.session_id for session in user_1_sessions]

    user_2_sessions = shared_db.get_sessions(session_type=SessionType.AGENT, user_id=user_2_id)
    assert len(user_2_sessions) == 1
    assert user_2_session_1_id in [session.session_id for session in user_2_sessions]

    # Verify memory DB has the right memories
    user_1_memories = shared_db.get_user_memories(user_id=user_1_id)
    assert len(user_1_memories) >= 1  # At least 1 memory for user 1

    user_2_memories = shared_db.get_user_memories(user_id=user_2_id)
    assert len(user_2_memories) >= 1  # At least 1 memory for user 2

    # Verify memory content for user 1
    user_1_memory_texts = [m.memory for m in user_1_memories]
    assert user_1_memory_texts is not None
    assert "Mark Gonzales" in user_1_memory_texts[0]
    assert "manga" in user_1_memory_texts[1]

    # Verify memory content for user 2
    user_2_memory_texts = [m.memory for m in user_2_memories]
    assert "John Doe" in user_2_memory_texts[0]
    assert "hike" in user_2_memory_texts[1] or "hiking" in user_2_memory_texts[1]
