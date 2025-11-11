"""Test AgentOS application for system testing."""
import os

from agno.agent.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg_async://agno:agno_test_password@localhost:5432/agentos_test")
CONTAINER_ID = os.getenv("CONTAINER_ID", "unknown")

# Create a shared PostgreSQL database
db = AsyncPostgresDb(
    db_url=DATABASE_URL,
)

# Create a simple test agent
test_agent = Agent(
    id="test-agent",
    name="Test Agent",
    description="A simple test agent for system testing",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    add_history_to_context=True,
    num_history_runs=5,
    instructions=[
        "You are a helpful test agent.",
        "Always mention that you are running in a stateless container.",
        f"Your container ID is: {CONTAINER_ID}",
    ],
    markdown=True,
)

# Create AgentOS instance
agent_os = AgentOS(
    id="test-os",
    name="Test AgentOS",
    description=f"Test AgentOS instance running in {CONTAINER_ID}",
    agents=[test_agent],
)

# Get the FastAPI app
app = agent_os.get_app()
