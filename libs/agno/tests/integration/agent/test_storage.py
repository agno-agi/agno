import uuid

import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.base import RunStatus


@pytest.fixture
def agent(shared_db):
    """Create an agent with db and memory for testing."""
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        markdown=True,
    )


@pytest.mark.asyncio
async def test_run_history_persistence(agent):
    """Test that all runs within a session are persisted in db."""
    user_id = "john@example.com"
    session_id = f"session_{uuid.uuid4()}"

    response = await agent.arun("Hello, how are you?", user_id=user_id, session_id=session_id)

    assert response.status == RunStatus.completed

    # Verify the stored session data after all turns
    agent_session = agent.get_session(session_id=session_id)

    assert agent_session is not None
    assert len(agent_session.runs) == 1
    assert agent_session.runs[0].status == RunStatus.completed
    assert agent_session.runs[0].messages is not None
    assert len(agent_session.runs[0].messages) == 3
    assert agent_session.runs[0].messages[1].content == "Hello, how are you?"
