"""Factory with Input Schema -- client-controlled agent parameters.

The client sends a `factory_input` JSON object in the run request. The factory
declares a pydantic model for validation. AgentOS validates the input and
exposes it as `ctx.input` (a typed pydantic instance).

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/agent/02_input_schema_factory.py

Test:
    # Run with default persona
    curl -X POST http://localhost:7777/agents/research-agent/runs \
        -F 'message=What are the latest trends in AI?' \
        -F 'user_id=user_1' \
        -F 'stream=false'

    # Run with custom persona and depth
    curl -X POST http://localhost:7777/agents/research-agent/runs \
        -F 'message=What are the latest trends in AI?' \
        -F 'user_id=user_1' \
        -F 'factory_input={"persona": "skeptic", "depth": 5}' \
        -F 'stream=false'

    # Invalid input returns 400
    curl -X POST http://localhost:7777/agents/research-agent/runs \
        -F 'message=Hello' \
        -F 'factory_input={"depth": "not_a_number"}' \
        -F 'stream=false'
"""

from typing import Literal

from agno.agent import Agent, AgentFactory
from agno.db.postgres import PostgresDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="factory-schema-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

PERSONAS = {
    "analyst": "You are a data-driven research analyst. Cite sources and use numbers.",
    "advisor": "You are a strategic advisor. Focus on actionable recommendations.",
    "skeptic": "You are a critical skeptic. Challenge assumptions and highlight risks.",
}


class ResearchInput(BaseModel):
    """Schema for factory_input -- validated by AgentOS before the factory runs."""

    persona: Literal["analyst", "advisor", "skeptic"] = "analyst"
    depth: int = 3


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_research_agent(ctx: RequestContext) -> Agent:
    """Build a research agent with the requested persona and depth."""
    cfg: ResearchInput = ctx.input

    return Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        db=db,
        instructions=(
            f"{PERSONAS[cfg.persona]}\n\n"
            f"Research depth: {cfg.depth} (higher = more thorough).\n"
            "Be concise but comprehensive."
        ),
        add_datetime_to_context=True,
        markdown=True,
    )


research_factory = AgentFactory(
    db=db,
    id="research-agent",
    name="Research Agent",
    description="Builds a research agent with configurable persona and depth",
    factory=build_research_agent,
    input_schema=ResearchInput,
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="factory-schema-demo",
    description="Demo: agent factory with pydantic input schema",
    agents=[research_factory],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="02_input_schema_factory:app", port=7777, reload=True)
