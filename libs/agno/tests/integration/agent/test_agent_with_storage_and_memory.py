import pytest

from agno.agent.agent import Agent
from agno.memory.agent import AgentMemory
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat


@pytest.fixture
def chat_agent(agent_storage, memory):
    """Create an agent with storage and memory for testing."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        memory=memory,
    )


@pytest.fixture
def memory_agent(agent_storage, memory):
    """Create an agent that creates memories."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        memory=memory,
        enable_user_memories=True,
    )


def test_agent_runs_in_memory(chat_agent):
    session_id = "test_session"
    response = chat_agent.run("Hello, how are you?", session_id=session_id)
    assert response is not None
    assert response.content is not None
    assert response.run_id is not None

    assert len(chat_agent.memory.runs[session_id]) == 1
    stored_run_response = chat_agent.memory.runs[session_id][0]
    assert stored_run_response.run_id == response.run_id
    assert len(stored_run_response.messages) == 2

    # Check that the run is also stored in the agent session
    assert len(chat_agent.agent_session.memory["runs"]) == 1


def test_agent_runs_in_memory_default_memory(agent_storage):
    # No memory is set on the agent
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        add_history_to_messages=True,
        num_history_runs=3,
    )
    session_id = "test_session"
    agent.run("What is the capital of France?", session_id=session_id)
    assert len(agent.memory.runs[session_id]) == 1
    assert len(agent.agent_session.memory["runs"]) == 1

    agent.run("What is the capital of Germany?", session_id=session_id)
    assert len(agent.memory.runs[session_id]) == 2
    assert len(agent.agent_session.memory["runs"]) == 2

    agent.run("What have I asked so far?", session_id=session_id)
    assert len(agent.memory.runs[session_id]) == 3
    assert len(agent.agent_session.memory["runs"]) == 3

    # New agent instance
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        add_history_to_messages=True,
        num_history_runs=3,
    )

    agent.run("What have I asked so far?", session_id=session_id)
    assert len(agent.memory.runs[session_id]) == 4
    assert len(agent.agent_session.memory["runs"]) == 4


def test_agent_runs_in_memory_legacy(chat_agent):
    chat_agent.memory = AgentMemory()
    session_id = "test_session"
    response = chat_agent.run(
        "What can you do?",
        messages=[
            Message(role="user", content="Hello, how are you?"),
            Message(role="assistant", content="I'm good, thank you!"),
        ],
        session_id=session_id,
    )
    assert response is not None
    assert response.content is not None
    assert response.run_id is not None

    assert len(chat_agent.memory.runs) == 1
    stored_agent_run = chat_agent.memory.runs[0]
    assert stored_agent_run.response.run_id == response.run_id
    assert len(stored_agent_run.response.messages) == 4
    assert len(stored_agent_run.messages) == 2

    # Check that the run is also stored in the agent session
    assert len(chat_agent.agent_session.memory["runs"]) == 1


@pytest.mark.asyncio
async def test_multi_user_multi_session_chat(memory_agent, agent_storage, memory):
    """Test multi-user multi-session chat with storage and memory."""
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

    # Chat with user 1 - Session 1
    await memory_agent.arun(
        "My name is Mark Gonzales and I like anime and video games.", user_id=user_1_id, session_id=user_1_session_1_id
    )
    await memory_agent.arun(
        "I also enjoy reading manga and playing video games.", user_id=user_1_id, session_id=user_1_session_1_id
    )

    # Chat with user 1 - Session 2
    await memory_agent.arun("I'm going to the movies tonight.", user_id=user_1_id, session_id=user_1_session_2_id)

    # Chat with user 2
    await memory_agent.arun("Hi my name is John Doe.", user_id=user_2_id, session_id=user_2_session_1_id)
    await memory_agent.arun(
        "I love hiking and go hiking every weekend.", user_id=user_2_id, session_id=user_2_session_1_id
    )

    # Chat with user 3
    await memory_agent.arun("Hi my name is Jane Smith.", user_id=user_3_id, session_id=user_3_session_1_id)
    await memory_agent.arun("I'm going to the gym tomorrow.", user_id=user_3_id, session_id=user_3_session_1_id)

    # Continue the conversation with user 1
    await memory_agent.arun("What do you suggest I do this weekend?", user_id=user_1_id, session_id=user_1_session_1_id)

    # Verify storage DB has the right sessions
    all_session_ids = agent_storage.get_all_session_ids()
    assert len(all_session_ids) == 4  # 4 sessions total

    # Check that each user has the expected sessions
    user_1_sessions = agent_storage.get_all_sessions(user_id=user_1_id)
    assert len(user_1_sessions) == 2
    assert user_1_session_1_id in [session.session_id for session in user_1_sessions]
    assert user_1_session_2_id in [session.session_id for session in user_1_sessions]

    user_2_sessions = agent_storage.get_all_sessions(user_id=user_2_id)
    assert len(user_2_sessions) == 1
    assert user_2_session_1_id in [session.session_id for session in user_2_sessions]

    user_3_sessions = agent_storage.get_all_sessions(user_id=user_3_id)
    assert len(user_3_sessions) == 1
    assert user_3_session_1_id in [session.session_id for session in user_3_sessions]

    # Verify memory DB has the right memories
    user_1_memories = memory.get_user_memories(user_id=user_1_id)
    assert len(user_1_memories) >= 1  # At least 1 memory for user 1

    user_2_memories = memory.get_user_memories(user_id=user_2_id)
    assert len(user_2_memories) >= 1  # At least 1 memory for user 2

    user_3_memories = memory.get_user_memories(user_id=user_3_id)
    assert len(user_3_memories) >= 1  # At least 1 memory for user 3

    # Verify memory content for user 1
    user_1_memory_texts = [m.memory for m in user_1_memories]
    assert any("Mark Gonzales" in text for text in user_1_memory_texts)
    assert any("anime" in text for text in user_1_memory_texts)
    assert any("video games" in text for text in user_1_memory_texts)
    assert any("manga" in text for text in user_1_memory_texts)

    # Verify memory content for user 2
    user_2_memory_texts = [m.memory for m in user_2_memories]
    assert any("John Doe" in text for text in user_2_memory_texts)
    assert any("hike" in text for text in user_2_memory_texts) or any("hiking" in text for text in user_2_memory_texts)

    # Verify memory content for user 3
    user_3_memory_texts = [m.memory for m in user_3_memories]
    assert any("Jane Smith" in text for text in user_3_memory_texts)
