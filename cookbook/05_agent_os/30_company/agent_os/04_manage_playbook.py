"""
Manage a Company Playbook in AgentOS
====================================

Serve the playbook from ../04_manage_playbook.py: a Product status page and a
decision log that Product Manager can read and extend from chat.

Prerequisites: OPENAI_API_KEY for Product Manager chat.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/04_manage_playbook.py
Try: GET http://localhost:7777/company/wiki and /company/decisions
     Ask Product Manager: "Update the SDK status: release notes are in review."
     Then ask: "Log a decision to ship after one more review."
"""

from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(id="company-playbook-db", db_file="tmp/company_playbook.db")

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-playbook",
    description="Company playbook pages with version checks and a decision log.",
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
    manager.create(
        id="sdk", name="SDK", purpose="Build reliable agents", user_id="alice"
    )
    page = manager.read_wiki("sdk", "status.md")
    manager.write_wiki(
        product_id="sdk",
        path="status.md",
        content="# Status\n\nRelease proposed.\n",
        expected_version=page.metadata.version,
        user_id="alice",
    )
    manager.log_decision(
        decision="Review before release",
        reasoning="Human approval is required",
        user_id="alice",
    )


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    agent_os.serve(app=app)
