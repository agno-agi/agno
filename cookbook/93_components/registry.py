"""
Registry for Non-Serializable Components
========================================

Demonstrates using Registry to restore tools, models, and schemas when loading
components from the database.
"""

from agno.agent.agent import Agent, get_agent_by_id  # noqa: F401
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


# ---------------------------------------------------------------------------
# Create Registry Schemas and Tools
# ---------------------------------------------------------------------------
class BasicInputSchema(BaseModel):
    message: str


class BasicOutputSchema(BaseModel):
    message: str


class ComplexInputSchema(BaseModel):
    message: str
    name: str
    age: int


def sample_tool():
    return "Hello, world!"


# ---------------------------------------------------------------------------
# Create Registry
# ---------------------------------------------------------------------------
registry = Registry(
    name="Agno Registry",
    description="Registry for Agno",
    tools=[DuckDuckGoTools(), sample_tool],
    models=[OpenAIChat(id="gpt-5-mini")],
    dbs=[db],
    schemas=[BasicInputSchema, BasicOutputSchema, ComplexInputSchema],
)

# ---------------------------------------------------------------------------
# Run Registry Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Uncomment this during your first run to save the agent to the database
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        tools=[DuckDuckGoTools(), sample_tool],
        output_schema=BasicOutputSchema,
    )
    agent.save()

    # agent = get_agent_by_id(db=db, id="registry-agent", registry=registry)
    # agent.print_response("Call the sample tool")
