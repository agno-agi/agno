import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.models.openai import OpenAIChat
from agno.models.openai.responses import OpenAIResponses
from agno.os import AgentOS
from agno.os.routers.agents.schema import AgentResponse
from agno.team.team import Team


@pytest.mark.asyncio
async def test_agent_response_normalizes_openai_chat_provider():
    agent = Agent(id="agent-chat", name="agent-chat", model=OpenAIChat(id="gpt-4o"))

    response = await AgentResponse.from_agent(agent)

    assert response.model is not None
    assert response.model.provider == "openai"


@pytest.mark.asyncio
async def test_agent_response_normalizes_openai_responses_provider():
    agent = Agent(id="agent-responses", name="agent-responses", model=OpenAIResponses(id="gpt-4.1"))

    response = await AgentResponse.from_agent(agent)

    assert response.model is not None
    assert response.model.provider == "openai-responses"


@pytest.mark.asyncio
async def test_agent_response_normalizes_azure_provider():
    agent = Agent(id="agent-azure", name="agent-azure", model=AzureOpenAI(id="gpt-4o"))

    response = await AgentResponse.from_agent(agent)

    assert response.model is not None
    assert response.model.provider == "azure-openai"


def test_models_endpoint_normalizes_provider_keys():
    agent = Agent(id="agent-chat", name="agent-chat", model=OpenAIChat(id="gpt-4o"))
    team = Team(id="team-azure", name="team-azure", members=[agent], model=AzureOpenAI(id="gpt-4o"))
    agent_os = AgentOS(
        agents=[agent, Agent(id="agent-responses", name="agent-responses", model=OpenAIResponses(id="gpt-4.1"))],
        teams=[team],
    )

    client = TestClient(agent_os.get_app())
    response = client.get("/models")

    assert response.status_code == 200
    models = response.json()
    assert {"id": "gpt-4o", "provider": "openai"} in models
    assert {"id": "gpt-4.1", "provider": "openai-responses"} in models
    assert {"id": "gpt-4o", "provider": "azure-openai"} in models
