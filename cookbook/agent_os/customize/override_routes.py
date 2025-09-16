"""
Example AgentOS app with a custom FastAPI app with conflicting routes.

This example demonstrates the `replace_routes=False` functionality which allows your
custom routes to take precedence over conflicting AgentOS routes.

When `replace_routes=False`:
- Your custom routes (/, /health) will be preserved
- Conflicting AgentOS routes will be skipped
- Non-conflicting AgentOS routes will still be added

When `replace_routes=True` (default):
- AgentOS routes will override your custom routes
- Warnings will be logged about the conflicts
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

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

# Add Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Custom landing page (conflicts with AgentOS home route)
@app.get("/")
async def get_custom_home():
    return {
        "message": "Custom FastAPI App",
        "note": "Using replace_routes=True to preserve custom routes",
    }


# Custom health endpoint (conflicts with AgentOS health route)
@app.get("/health")
async def get_custom_health():
    return {"status": "custom_ok", "note": "This is your custom health endpoint"}


# Setup our AgentOS app by passing your FastAPI app
# Use replace_routes=False to preserve your custom routes over AgentOS routes
agent_os = AgentOS(
    description="Example app with route replacement",
    agents=[web_research_agent],
    fastapi_app=app,
    replace_routes=False,  # Skip conflicting AgentOS routes, keep your custom routes
)

app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    With replace_routes=True:
    - Your custom routes are preserved: http://localhost:7777/ and http://localhost:7777/health
    - AgentOS routes are available at other paths: http://localhost:7777/sessions, etc.
    - Conflicting AgentOS routes (GET / and GET /health) are skipped
    - API docs: http://localhost:7777/docs

    Try changing replace_routes=False to see AgentOS routes override your custom ones.
    """
    agent_os.serve(app="override_routes:app", reload=True)
