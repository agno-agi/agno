"""Basic Agent Factory -- per-tenant agent construction.

Demonstrates the simplest factory pattern: a callable that receives a
RequestContext and returns a fresh Agent with tenant-specific instructions.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/factories/agent/01_basic_factory.py

Test:
    # List agents (factory shows up with is_factory: true)
    curl http://localhost:7777/agents

    # Run the factory agent
    curl -X POST http://localhost:7777/agents/tenant-agent/runs \
        -F 'message=Hello, who are you?' \
        -F 'user_id=tenant_42' \
        -F 'stream=false'
"""

from agno.agent import Agent, AgentFactory
from agno.db.postgres import PostgresDb
from agno.factory import RequestContext
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="factory-demo-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Factory: build a per-tenant agent
# ---------------------------------------------------------------------------


def build_tenant_agent(ctx: RequestContext) -> Agent:
    """Called on every request. Returns a fresh Agent for the calling tenant."""
    user_id = ctx.user_id or "anonymous"
    return Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        db=db,
        instructions=f"You are a helpful assistant for tenant {user_id}. Be concise.",
        add_datetime_to_context=True,
        markdown=True,
    )


tenant_factory = AgentFactory(
    db=db,
    id="tenant-agent",
    name="Per-tenant assistant",
    description="Builds a personalized agent per tenant on each request",
    factory=build_tenant_agent,
)

# ---------------------------------------------------------------------------
# A normal (prototype) agent alongside the factory
# ---------------------------------------------------------------------------

static_agent = Agent(
    id="support-agent",
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    instructions="You are a general support agent. Be concise.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS -- factories and prototypes coexist
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="factory-basic-demo",
    description="Demo: basic agent factory alongside a static agent",
    agents=[static_agent, tenant_factory],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="01_basic_factory:app", port=7777, reload=True)
