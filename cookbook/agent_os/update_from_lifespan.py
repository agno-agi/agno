from contextlib import asynccontextmanager

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS

# First agent. We will add this to the AgentOS on initialization.
agent1 = Agent(
    id="first-agent",
    name="First Agent",
    markdown=True,
)

# Second agent. We will add this to the AgentOS in the lifespan function.
agent2 = Agent(
    id="second-agent",
    name="Second Agent",
    markdown=True,
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
)


# Lifespan function receiving the AgentOS instance as parameter.
@asynccontextmanager
async def lifespan(app, agent_os):
    # Add the new Agent
    agent_os.agents.append(agent2)

    # Resync the AgentOS
    agent_os.resync()

    yield


# Setup our AgentOS with the lifespan function and the first agent.
agent_os = AgentOS(
    lifespan=lifespan,
    agents=[agent1],
)

# Get our app.
app = agent_os.get_app()

# Serve the app.
if __name__ == "__main__":
    agent_os.serve(app="update_from_lifespan:app", reload=True)
