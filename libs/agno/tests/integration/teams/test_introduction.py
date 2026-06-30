import uuid

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


def test_team_with_introduction(shared_db):
    """Test that introduction is added to the session as the first assistant message."""
    session_id = str(uuid.uuid4())
    introduction_text = "Hello! I'm your helpful assistant. I can help you with various tasks."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    # First run
    response = team.run("What can you help me with?")

    assert response is not None
    assert response.content is not None

    # Verify introduction was stored in the session
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2  # Introduction + actual run

    # Verify introduction is the first run
    introduction_run = session.runs[0]
    assert introduction_run.content == introduction_text
    assert len(introduction_run.messages) == 1
    assert introduction_run.messages[0].role == "assistant"
    assert introduction_run.messages[0].content == introduction_text


def test_team_introduction_only_added_once(shared_db):
    """Test that introduction is only added once, not on subsequent runs."""
    session_id = str(uuid.uuid4())
    introduction_text = "Welcome! I'm here to help."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    # First run
    team.run("Hello")

    # Get session after first run
    session_after_first = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert len(session_after_first.runs) == 2  # Introduction + first run

    # Second run
    team.run("How are you?")

    # Get session after second run
    session_after_second = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert len(session_after_second.runs) == 3  # Introduction + first run + second run

    # Verify introduction is still the first run and hasn't been duplicated
    assert session_after_second.runs[0].content == introduction_text
    assert session_after_second.runs[0].messages[0].role == "assistant"


def test_team_introduction_with_chat_history(shared_db):
    """Test that introduction works correctly with add_history_to_context."""
    session_id = str(uuid.uuid4())
    introduction_text = "I'm a specialized assistant for Python programming."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
        add_history_to_context=True,
        num_history_runs=5,
    )

    # First interaction
    response1 = team.run("Tell me about Python lists")
    assert response1 is not None

    # Second interaction - should have access to introduction and first message
    response2 = team.run("What did you introduce yourself as?")
    assert response2 is not None

    # Verify session structure
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 3  # Introduction + 2 runs
    assert session.runs[0].content == introduction_text


def test_team_introduction_streaming(shared_db):
    """Test that introduction works with streaming mode."""
    session_id = str(uuid.uuid4())
    introduction_text = "Hello! Streaming assistant here."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    # Run with streaming
    response_chunks = []
    for chunk in team.run("Hi there!", stream=True):
        response_chunks.append(chunk)

    assert len(response_chunks) > 0

    # Verify introduction was stored
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2  # Introduction + streamed run
    assert session.runs[0].content == introduction_text
    assert session.runs[0].messages[0].role == "assistant"


async def test_team_introduction_async(shared_db):
    """Test that introduction works with async mode."""
    session_id = str(uuid.uuid4())
    introduction_text = "Async assistant at your service!"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    # Async run
    response = await team.arun("Hello!")

    assert response is not None
    assert response.content is not None

    # Verify introduction was stored
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2  # Introduction + async run
    assert session.runs[0].content == introduction_text
    assert session.runs[0].messages[0].role == "assistant"
    assert session.runs[0].messages[0].content == introduction_text


async def test_team_introduction_async_streaming(shared_db):
    """Test that introduction works with async streaming mode."""
    session_id = str(uuid.uuid4())
    introduction_text = "Async streaming assistant ready!"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    # Async streaming run
    response_chunks = []
    async for chunk in team.arun("Hello there!", stream=True):
        response_chunks.append(chunk)

    assert len(response_chunks) > 0

    # Verify introduction was stored
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2  # Introduction + async streamed run
    assert session.runs[0].content == introduction_text
    assert session.runs[0].messages[0].role == "assistant"


def test_team_without_introduction(shared_db):
    """Test that team works normally without introduction."""
    session_id = str(uuid.uuid4())

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=None,  # Explicitly no introduction
    )

    response = team.run("Hello!")

    assert response is not None

    # Verify no introduction run was created
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 1  # Only the actual run, no introduction


def test_team_introduction_with_different_sessions(shared_db):
    """Test that introduction is added to each new session."""
    introduction_text = "I'm your multi-session assistant."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        members=[agent],
        introduction=introduction_text,
    )

    # First session
    session_id_1 = str(uuid.uuid4())
    team.run("Hello from session 1", session_id=session_id_1)

    session_1 = shared_db.get_session(session_id=session_id_1, session_type=SessionType.TEAM)
    assert session_1 is not None
    assert len(session_1.runs) == 2  # Introduction + run
    assert session_1.runs[0].content == introduction_text

    # Second session
    session_id_2 = str(uuid.uuid4())
    team.run("Hello from session 2", session_id=session_id_2)

    session_2 = shared_db.get_session(session_id=session_id_2, session_type=SessionType.TEAM)
    assert session_2 is not None
    assert len(session_2.runs) == 2  # Introduction + run
    assert session_2.runs[0].content == introduction_text


def test_team_introduction_multiline(shared_db):
    """Test that multiline introduction text is handled correctly."""
    session_id = str(uuid.uuid4())
    introduction_text = """Hello! I'm your personal assistant.
I can help you with:
- Programming questions
- General knowledge
- Task planning

How can I assist you today?"""

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    response = team.run("What can you do?")

    assert response is not None

    # Verify multiline introduction was stored correctly
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2
    assert session.runs[0].content == introduction_text
    assert "Programming questions" in session.runs[0].content
    assert "General knowledge" in session.runs[0].content


def test_team_get_chat_history_with_introduction(shared_db):
    """Test that get_chat_history includes the introduction message."""
    session_id = str(uuid.uuid4())
    introduction_text = "I'm your chat history assistant."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
    )

    # Make a few runs
    team.run("First message")
    team.run("Second message")

    # Get chat history
    chat_history = team.get_chat_history(session_id=session_id)

    assert chat_history is not None
    # Introduction +  (2 user messages + 2 assistant responses)
    # System messages are included in team runs
    assert len(chat_history) >= 5

    # First message should be the introduction from assistant
    assert chat_history[0].role == "assistant"
    assert chat_history[0].content == introduction_text


def test_team_introduction_with_system_message(shared_db):
    """Test that introduction works correctly with a custom system_message."""
    session_id = str(uuid.uuid4())
    introduction_text = "Hello! I'm a specialized Python assistant."
    system_message_text = "You are a Python programming expert. Always provide code examples."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
        system_message=system_message_text,
    )

    # Run team
    response = team.run("What do you do?")

    assert response is not None
    assert response.content is not None

    # Verify introduction was stored in the session
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2  # Introduction + actual run

    # Verify introduction is the first run
    introduction_run = session.runs[0]
    assert introduction_run.content == introduction_text
    assert introduction_run.messages[0].role == "assistant"
    assert introduction_run.messages[0].content == introduction_text


def test_team_introduction_with_system_message_callable(shared_db):
    """Test that introduction works with a system_message as a callable."""
    session_id = str(uuid.uuid4())
    introduction_text = "Welcome! I'm your dynamic assistant."

    def dynamic_system_message(team):
        return f"You are {team.name}. Provide helpful responses."

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="DynamicBot",
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_id=session_id,
        members=[agent],
        introduction=introduction_text,
        system_message=dynamic_system_message,
    )

    response = team.run("Tell me about yourself")

    assert response is not None

    # Verify introduction was stored
    session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    assert session is not None
    assert len(session.runs) == 2
    assert session.runs[0].content == introduction_text
    assert session.runs[0].messages[0].role == "assistant"
