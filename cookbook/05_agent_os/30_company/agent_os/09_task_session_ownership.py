"""
Share Task Sessions in AgentOS
==============================

Serve the setup from ../09_task_session_ownership.py with JWT authorization
and user isolation. Alice owns an accepted Task; Bob can start the next
attempt, and every run stays in Alice's durable Task session.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh), psycopg and PyJWT.
OPENAI_API_KEY is needed only for Product Manager chat; the workflow is local.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/09_task_session_ownership.py
Try: Copy the printed tokens into an Authorization header, then
     POST /company/tasks/{id}/runs as Alice, wait for review, and
     POST /company/tasks/{id}/runs with {"attempt": 2} as Bob.
     GET /company/tasks/{id}/runs shows both runs owned by Alice.
"""

import json
import time
from os import getenv

import jwt
from agno.company import CompanyManager
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.workflow import Step, StepInput, StepOutput, Workflow

# Local development secret; never reuse it outside this example.
SECRET = "local-cookbook-only-secret-at-least-32-bytes"
SCOPES = [
    "products:read",
    "products:write",
    "projects:read",
    "projects:write",
    "tasks:read",
    "tasks:write",
    "wiki:read",
    "workflows:run",
]

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="company-ownership-db",
    db_url=getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_ownership",
)


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
def draft(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Reviewed draft: " + json.loads(step_input.input)["brief"]
    )


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
    id="task-ownership",
    description="Collaborators revise one Task through its owner's session.",
    db=db,
    workflows=[workflow],
    company=CompanyConfig(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        automation_history_retention_days=30,
    ),
    authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
    user_isolation=True,
    queue=QueueConfig(durable=True, db=db),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Seed demo records and tokens
# ---------------------------------------------------------------------------
def token(user: str) -> str:
    claims = {
        "sub": user,
        "aud": "task-ownership",
        "scopes": SCOPES,
        "exp": int(time.time()) + 86400,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def seed() -> None:
    manager = CompanyManager(db, registry=agent_os.registry)
    if manager.get("sdk", include_deleted=True) is not None:
        return
    manager.create(id="sdk", name="SDK", user_id="alice")
    project = manager.create_project(product_id="sdk", name="Release", user_id="alice")
    task = manager.create_task(
        product_id="sdk",
        project_id=project["id"],
        title="Release notes",
        brief="Summarize reviewed changes",
        user_id="alice",
    )
    manager.transition_task(
        task_id=task["id"],
        target="ready",
        reason="Scope agreed",
        accepted_by="alice",
        executor_type="workflow",
        executor_id="draft",
    )


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    for user in ["alice", "bob"]:
        print(user + ": Bearer " + token(user))
    agent_os.serve(app=app)
