"""
Example AgentOS app with a custom health endpoint.

This example demonstrates the `health_endpoint` parameter which allows you to customize the health endpoint.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.os.routers.health import get_health_router
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

web_research_agent = Agent(
    id="web-research-agent",
    name="Web Research Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# Custom FastAPI app
app: FastAPI = FastAPI(
    title="Custom FastAPI App",
    version="1.0.0",
)


# Custom health endpoint
health_router = get_health_router(health_endpoint="/health-check")
app.include_router(health_router)


# Setup our AgentOS app by passing your FastAPI app in the app_config parameter
agent_os = AgentOS(
    description="Example app with custom health endpoint",
    agents=[web_research_agent],
    base_app=app,
)

app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    With on_route_conflict="preserve_base_app":
    - Your custom routes are preserved: http://localhost:7777/ and http://localhost:7777/health
    - AgentOS routes are available at other paths: http://localhost:7777/sessions, etc.
    - Conflicting AgentOS routes (GET / and GET /health) are skipped
    - API docs: http://localhost:7777/docs

    Try changing on_route_conflict="preserve_agentos" to see AgentOS routes override your custom ones. This is the default behavior.
    """
    agent_os.serve(app="custom_health_endpoint:app", reload=True)
