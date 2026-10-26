"""
Manage Company Projects in AgentOS
==================================

Serve the Projects from ../02_manage_projects.py: one finished Project and one
proposed Project waiting for a human to accept its scope.

Prerequisites: OPENAI_API_KEY for Product Manager chat.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/02_manage_projects.py
Try: GET http://localhost:7777/company/projects?status=proposed
     POST /company/projects/{id}/transitions with
     {"target": "active", "reason": "Scope agreed"}
     Ask Product Manager: "What is still proposed for the SDK?"
"""

from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(id="company-projects-db", db_file="tmp/company_projects.db")

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-projects",
    description="Company Projects with explicit transitions, soft delete and restore.",
    db=db,
    company=CompanyConfig(model=OpenAIResponses(id="gpt-5.6-luna")),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Seed demo records
# ---------------------------------------------------------------------------
def seed() -> None:
    manager = CompanyManager(db)
    if manager.get("sdk", include_deleted=True) is not None:
        return
    manager.create(id="sdk", name="SDK", purpose="Build the framework", user_id="alice")
    shipped = manager.create_project(
        product_id="sdk", name="Ship release", user_id="alice"
    )
    manager.transition_project(
        project_id=shipped["id"],
        target="active",
        reason="Scope agreed",
        accepted_by="alice",
    )
    manager.transition_project(
        project_id=shipped["id"],
        target="done",
        reason="Outcome achieved",
        accepted_by="alice",
    )
    manager.create_project(product_id="sdk", name="Plan next release", user_id="bob")


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    agent_os.serve(app=app)
