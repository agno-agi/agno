"""
Manage Company Tasks in AgentOS
===============================

Serve the Tasks from ../03_manage_tasks.py with a registered writer agent, so
Tasks can be accepted for it and moved through review in the AgentOS UI.

Prerequisites: OPENAI_API_KEY for the writer and Product Manager chat.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/03_manage_tasks.py
Try: POST http://localhost:7777/company/tasks/{id}/transitions with
     {"target": "ready", "reason": "Scope agreed",
      "executor_type": "agent", "executor_id": "writer"}
     Then PATCH the accepted Task's brief; the frozen scope is refused.
"""

from agno.agent import Agent
from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(id="company-tasks-db", db_file="tmp/company_tasks.db")
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

writer = Agent(
    id="writer",
    name="Writer",
    model=model,
    db=db,
    instructions="Write concise release notes from the Task brief.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-tasks",
    description="Company Tasks with executor acceptance, frozen scope and review.",
    db=db,
    agents=[writer],
    company=CompanyConfig(model=model),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Seed demo records
# ---------------------------------------------------------------------------
def seed() -> None:
    manager = CompanyManager(db, registry=agent_os.registry)
    if manager.get("sdk", include_deleted=True) is not None:
        return
    manager.create(id="sdk", name="SDK", purpose="Build the framework", user_id="alice")
    project = manager.create_project(product_id="sdk", name="Release")
    manager.create_task(
        product_id="sdk",
        title="Ship release",
        brief="Write the release notes",
        project_id=project["id"],
        user_id="alice",
    )
    manager.create_task(
        product_id="sdk",
        title="Plan next release",
        project_id=project["id"],
        user_id="bob",
    )


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    agent_os.serve(app=app)
