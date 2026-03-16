"""
Cookbook: Code-defined agents available to UI-built workflows.

This sets up an AgentOS with code-defined agents. When a user builds a
workflow through the UI:

1. The UI fetches available agents from /registry (code-defined) and
   /components (DB-stored) to populate the step agent dropdown.
2. The user selects a code-defined agent (e.g. "research-agent") for a step.
3. The workflow is saved to DB with just the agent_id reference.
4. When the workflow is loaded back, Step.from_dict() resolves the agent
   from the Registry first, falling back to DB only if not found.

The agents below are never saved to the database -- they live in memory
via the Registry, which AgentOS auto-populates on startup.

Important: Code-defined agents MUST have explicit, stable `id` values.
The UI stores these IDs in the workflow config. If the ID changes between
restarts, the workflow will fail to resolve the agent.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Code-defined agents with stable IDs.
# These appear in the UI workflow builder via the /registry endpoint.
# They are NOT saved to the database.
research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Research topics and extract key insights",
)

writer_agent = Agent(
    id="writer-agent",
    name="Writer Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Write content based on research",
)

# AgentOS auto-populates its registry with these agents.
# The /registry?resource_type=agent endpoint exposes them to the UI.
# Workflows built in the UI that reference these agents by ID will
# resolve them from the registry when loaded from DB.
agent_os = AgentOS(
    description="Demo: code-defined agents available to UI workflow builder",
    db=db,
    agents=[research_agent, writer_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="registry_agents_in_workflow:app", reload=True)
