"""
Cookbook: Using code-defined agents in DB-saved workflows via Registry.

This demonstrates how a workflow saved to the database can reference
code-defined agents. When the workflow is loaded back, Step.from_dict()
resolves agents from the Registry (populated by AgentOS) before falling
back to the database.

Steps:
1. Define agents in code (not saved to DB)
2. Save a workflow that references those agents by ID
3. Load the workflow back via AgentOS -- agents are resolved from the registry
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# -- Code-defined agents (never saved to DB) --
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

# -- Build and save a workflow that references these agents by ID --
workflow = Workflow(
    id="registry-demo-workflow",
    name="Registry Demo Workflow",
    description="Workflow whose steps reference code-defined agents",
    db=db,
    steps=[
        Step(name="Research", agent=research_agent),
        Step(name="Write", agent=writer_agent),
    ],
)

# Save workflow config to DB. The steps store agent_id references, not full agent configs.
version = workflow.save(db=db)
print(f"Saved workflow as version {version}")

# -- AgentOS auto-populates the registry with code-defined agents --
# When the workflow is loaded from DB, Step.from_dict() finds the agents
# in the registry instead of looking them up in the DB (where they don't exist).
agent_os = AgentOS(
    description="Demo: registry agents in workflows",
    agents=[research_agent, writer_agent],
    workflows=[workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="registry_agents_in_workflow:app", reload=True)
