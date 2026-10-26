"""
Execute Company Tasks in AgentOS
================================

Serve the durable Task queue from ../06_execute_tasks.py with the scheduler on,
so accepting a Task for the draft workflow runs it and moves it to review.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and psycopg.
OPENAI_API_KEY is needed only for Product Manager chat; the workflow is local.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/06_execute_tasks.py
Try: POST http://localhost:7777/company/tasks/{id}/transitions with
     {"target": "ready", "reason": "Scope agreed",
      "executor_type": "workflow", "executor_id": "draft"}
     Then POST /company/tasks/{id}/runs, or wait about a minute for the
     scheduler, and open GET /company/attention to see the Task in review.
"""

import json
from os import getenv

from agno.company import CompanyManager
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.workflow import Step, StepInput, StepOutput, Workflow

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="company-execute-db",
    db_url=getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_execute",
)


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
def draft(step_input: StepInput) -> StepOutput:
    context = json.loads(step_input.input)
    return StepOutput(content="Draft ready for review: " + context["brief"])


workflow = Workflow(
    id="draft",
    name="Draft",
    db=db,
    steps=[Step(name="Draft", executor=draft)],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-execute",
    description="Accepted Company Tasks run through the durable queue.",
    db=db,
    workflows=[workflow],
    company=CompanyConfig(model=OpenAIResponses(id="gpt-5.6-luna")),
    queue=QueueConfig(durable=True, db=db),
    scheduler=True,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Seed demo records
# ---------------------------------------------------------------------------
def seed() -> None:
    manager = CompanyManager(db, registry=agent_os.registry)
    if manager.get("sdk", include_deleted=True) is not None:
        return
    manager.create(id="sdk", name="SDK", purpose="Build the framework")
    project = manager.create_project(product_id="sdk", name="Release")
    manager.create_task(
        product_id="sdk",
        project_id=project["id"],
        title="Draft release notes",
        brief="Summarize reviewed changes",
        evidence=[{"reference": "Reviewed release changes"}],
    )


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    agent_os.serve(app=app)
