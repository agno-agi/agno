import uuid

import pytest

from agno.agent import RemoteAgent
from agno.team import RemoteTeam
from agno.utils.http import aclose_default_clients
from agno.workflow import RemoteWorkflow

from .test_utils import generate_jwt_token

REQUEST_TIMEOUT = 60.0

# A2A team and workflow IDs (exposed by gateway via A2A interface)
A2A_AGENT_ID = "assistant-agent-2"
A2A_TEAM_ID = "research-team-2"
A2A_WORKFLOW_ID = "qa-workflow-2"


@pytest.fixture(scope="module")
def a2a_base_url(agno_a2a_url: str) -> str:
    """Get the A2A endpoint URL."""
    return f"{agno_a2a_url}/a2a"


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def token(test_user_id: str) -> str:
    return generate_jwt_token(user_id=test_user_id)


@pytest.fixture(autouse=True)
async def cleanup_http_clients():
    """Cleanup HTTP clients after each test to prevent event loop closure issues."""
    yield
    try:
        await aclose_default_clients()
    except RuntimeError:
        # Event loop may already be closed, ignore
        pass


@pytest.mark.asyncio
async def test_a2a_remote_agent_basic_messaging(a2a_base_url: str, token: str):
    """Test basic non-streaming message via A2A protocol to RemoteAgent."""
    # Create RemoteAgent with A2A protocol
    remote_agent = RemoteAgent(
        base_url=f"{a2a_base_url}/agents/{A2A_AGENT_ID}",
        agent_id=A2A_AGENT_ID,
        protocol="a2a",
        timeout=REQUEST_TIMEOUT,
    )

    # Send message via A2A protocol
    result = await remote_agent.arun(
        input="What is 2 + 2?",
        stream=False,
        auth_token=token,
    )

    # Verify response
    assert result is not None
    assert result.content is not None
    assert result.run_id is not None


@pytest.mark.asyncio
async def test_a2a_remote_team_basic_messaging(a2a_base_url: str, token: str):
    """Test basic non-streaming message via A2A protocol to RemoteTeam."""
    # Create RemoteTeam with A2A protocol
    remote_team = RemoteTeam(
        base_url=f"{a2a_base_url}/teams/{A2A_TEAM_ID}",
        team_id=A2A_TEAM_ID,
        protocol="a2a",
        timeout=REQUEST_TIMEOUT,
    )

    # Send message via A2A protocol
    result = await remote_team.arun(
        input="What is 2 + 2?",
        stream=False,
        auth_token=token,
    )

    # Verify response
    assert result is not None
    assert result.content is not None
    assert result.run_id is not None


@pytest.mark.asyncio
async def test_a2a_remote_workflow_basic_messaging(a2a_base_url: str, token: str):
    """Test basic non-streaming message via A2A protocol to RemoteWorkflow."""
    # Create RemoteWorkflow with A2A protocol
    remote_workflow = RemoteWorkflow(
        base_url=f"{a2a_base_url}/workflows/{A2A_WORKFLOW_ID}",
        workflow_id=A2A_WORKFLOW_ID,
        protocol="a2a",
        timeout=REQUEST_TIMEOUT,
    )

    # Send message via A2A protocol
    result = await remote_workflow.arun(
        input="What is the capital of France?",
        stream=False,
        auth_token=token,
    )

    # Verify response
    assert result is not None
    assert result.content is not None
    assert result.run_id is not None
