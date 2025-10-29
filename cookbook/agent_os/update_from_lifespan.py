from contextlib import asynccontextmanager

from agno.agent.agent import Agent
from agno.os import AgentOS

# Setup basic agents, teams and workflows
agent1 = Agent(
    id="first-agent",
    name="First Agent",
    markdown=True,
)
agent2 = Agent(
    id="second-agent",
    name="Second Agent",
    markdown=True,
)


@asynccontextmanager
async def lifespan(app, agent_os):
    agent_os.agents.append(agent2)
    agent_os._initialize_agents()
    yield


agent_os = AgentOS(
    lifespan=lifespan,
    agents=[agent1],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="update_from_lifespan:app", reload=True)
