"""
Run a Custom Routine in AgentOS
===============================

Serve the template-free Routine from ../08_custom_routines.py. The researcher
follows the Routine's own instructions and saves the website Sources it finds.

Prerequisites: OPENAI_API_KEY, croniter and pytz.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/08_custom_routines.py
Try: GET http://localhost:7777/company/routines, then
     POST /company/routines/{id}/trigger and check GET /company/sources.
     PATCH the Routine with {"cron_expr": "0 9 * * *"} to schedule it.
"""

from agno.agent import Agent
from agno.company import Product, Routine
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.tools.company import CompanyTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(id="company-routines-db", db_file="tmp/company_routines.db")
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=model,
    db=db,
    tools=[CompanyTools(db)],
)

# ---------------------------------------------------------------------------
# Declare Product
# ---------------------------------------------------------------------------

product = Product(
    id="research",
    name="Research",
    routines=[
        Routine(
            name="watch",
            executor_type="agent",
            executor_id="researcher",
            instructions="Find relevant release pages. Save useful website Sources. Read selected pages and "
            "propose evidence-backed Tasks only for actionable changes. A quiet check needs no Task.",
        )
    ],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-routines",
    description="A template-free Routine that discovers website Sources.",
    db=db,
    agents=[researcher],
    company=CompanyConfig(model=model, products=[product]),
    scheduler=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
