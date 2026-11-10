"""
AgentOS Research App - Deploy Your Parallel Agent
=================================================

Wrap a Parallel-powered research agent in AgentOS to get a production API
and the AgentOS control plane in a few lines. Run this file and open
http://localhost:7777 to chat with the agent or call its REST API.

Because this filename starts with a number, we pass the FastAPI app object to
serve() directly (live reload would need an importable "module:app" string).

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Create the Agent and AgentOS app
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/parallel_os.db")

research_agent = Agent(
    name="Parallel Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_search=True, enable_extract=True, enable_task=True)],
    db=db,
    add_history_to_context=True,
    markdown=True,
    instructions=[
        "You are a web research agent powered by Parallel.",
        "Use Search and Extract for fast lookups and the Task API for deep, "
        "cited research.",
    ],
)

agent_os = AgentOS(
    description="Parallel-powered research app",
    agents=[research_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the App
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Open http://localhost:7777 (API docs at /docs, config at /config).
    agent_os.serve(app=app)
