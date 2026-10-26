"""
Run a Product Heartbeat in AgentOS
==================================

Serve the heartbeat from ../07_heartbeat.py with the scheduler on. A source
reader agent runs the intake Routine against a local markdown Source and
proposes evidence-backed Backlog Tasks.

Prerequisites: OPENAI_API_KEY, croniter and pytz.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/07_heartbeat.py
Try: GET http://localhost:7777/company/routines, then
     POST /company/routines/{id}/trigger to run intake now.
     Edit tmp/company_heartbeat/release.md and trigger again; the same issue
     keeps one Backlog Task.
"""

from pathlib import Path

from agno.agent import Agent
from agno.company import Product, Routine, Source
from agno.company.routines import load_routine_skills
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.tools.company import CompanyTools

# ---------------------------------------------------------------------------
# Create Database and Source
# ---------------------------------------------------------------------------

directory = Path("tmp/company_heartbeat")
directory.mkdir(parents=True, exist_ok=True)
release = directory / "release.md"
if not release.exists():
    release.write_text("# Release\nDocument the new API.\n")

db = SqliteDb(id="company-heartbeat-db", db_file=str(directory / "company.db"))
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

reader = Agent(
    id="source-reader",
    name="Source Reader",
    model=model,
    db=db,
    tools=[CompanyTools(db)],
    skills=load_routine_skills(),
)

# ---------------------------------------------------------------------------
# Declare Product
# ---------------------------------------------------------------------------

product = Product(
    id="documentation",
    name="Documentation",
    purpose="Keep docs current with released SDK behavior",
    sources=[Source(type="markdown", reference=str(release.resolve()))],
    routines=[
        Routine(
            name="intake",
            template="intake",
            executor_type="agent",
            executor_id=reader.id,
            cron_expr="0 9 * * 1-5",
        )
    ],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-heartbeat",
    description="A weekday intake Routine reads a Source and proposes Tasks.",
    db=db,
    agents=[reader],
    company=CompanyConfig(model=model, products=[product]),
    scheduler=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
