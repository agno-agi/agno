"""
Example AgentOS app where the agent has a custom lifespan.
"""

from contextlib import asynccontextmanager

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.utils.log import log_info

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Setup basic agents, teams and workflows
agno_support_agent = Agent(
    id="example-agent",
    name="Example Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    markdown=True,
)


@asynccontextmanager
async def lifespan(app):
    log_info("Starting My FastAPI App")
    yield
    log_info("Stopping My FastAPI App")


agent_os = AgentOS(
    description="Example app with custom lifespan",
    agents=[agno_support_agent],
    lifespan=lifespan,
)


app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    You can see test your AgentOS at:
    http://localhost:7777/docs

    """
    # Don't use reload=True here, this can cause issues with the lifespan
    agent_os.serve(app="custom_lifespan:app")
