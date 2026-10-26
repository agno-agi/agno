"""
Archive Company Hierarchies in AgentOS
======================================

Serve the hierarchy from ../07_cascading_archive.py: a Product with an
accepted Task that blocks archiving until it is cancelled.

Prerequisites: OPENAI_API_KEY for the writer and Product Manager chat.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/07_cascading_archive.py
Try: DELETE http://localhost:7777/company/products/documentation; the response
     names the active Task. Cancel it with POST /company/tasks/{id}/transitions
     {"target": "cancelled", "reason": "Defer this release"}, archive again,
     then POST /company/products/documentation/restore.
"""

from agno.agent import Agent
from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(id="company-archive-db", db_file="tmp/company_archive.db")
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

writer = Agent(
    id="writer",
    name="Writer",
    model=model,
    db=db,
    instructions="Write the guide described in the Task brief.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-archive",
    description="Cascading archive and exact restore of Company work.",
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
    if manager.get("documentation", include_deleted=True) is not None:
        return
    manager.create(id="documentation", name="Documentation")
    first = manager.create_project(product_id="documentation", name="Release guide")
    second = manager.create_project(product_id="documentation", name="Next release")
    old = manager.create_task(
        product_id="documentation", title="Superseded draft", project_id=first["id"]
    )
    # Archived before the Product, so restoring the Product leaves it archived.
    manager.delete_task(old["id"])
    task = manager.create_task(
        product_id="documentation", title="Write guide", project_id=second["id"]
    )
    manager.transition_task(
        task_id=task["id"],
        target="ready",
        reason="Scope agreed",
        executor_type="agent",
        executor_id="writer",
    )


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    agent_os.serve(app=app)
