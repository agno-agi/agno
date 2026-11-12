"""
Serve Super Agent in Slack
==========================

Serve AgentOS's built-in Super Agent in Slack. Start an accepted Company Task
and its result is posted back into the same thread. Sandbox only as written:
without authorization, every member of the Slack workspace drives Super Agent.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, PostgreSQL (./cookbook/scripts/run_pgvector.sh) for the durable queue
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/super_agent.py
Try in Slack: "Start the task <seeded id>" (printed once the server is up), then in the thread "What is its status?"
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, mpim:history, channels:history, groups:history
"""

import asyncio
import os
import threading
import time
from typing import Any, Dict

import httpx
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack
from agno.registry import Registry
from agno.workflow import Step, StepInput, StepOutput, Workflow

PORT = 7777


# ---------------------------------------------------------------------------
# A slow executor for the Task
# ---------------------------------------------------------------------------
async def investigate(step_input: StepInput) -> StepOutput:
    await asyncio.sleep(int(os.getenv("TASK_SECONDS", "60")))
    return StepOutput(
        content="Findings: the nightly export fails because the job uses the old IAM role."
    )


db = PostgresDb(
    id="slack-super-agent-db",
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="slack_super_agent",
)
investigator = Workflow(
    id="investigator",
    name="Investigator",
    description="Slow investigation executor for Tasks started from Slack.",
    db=db,
    steps=[Step(name="investigate", executor=investigate)],
)
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create Super Agent Slack AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="slack-super-agent-os",
    description="AgentOS serving its built-in Super Agent through Slack.",
    db=db,
    registry=Registry(workflows=[investigator]),
    workflows=[investigator],
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
)
# The manager exists only once AgentOS is constructed.
agent_os.interfaces.append(Slack(team=agent_os.manager))
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# A Task a person has already accepted
# ---------------------------------------------------------------------------
def create_accepted_task(client: Any) -> Dict[str, Any]:
    product = client.post("/company/products", json={"name": "Billing"}).json()
    project = client.post(
        "/company/projects",
        json={"product_id": product["id"], "name": "Export failures"},
    ).json()
    client.post(
        f"/company/projects/{project['id']}/transitions",
        json={"target": "active", "reason": "Approved"},
    )
    task = client.post(
        "/company/tasks",
        json={
            "product_id": product["id"],
            "project_id": project["id"],
            "title": "Investigate the nightly export failure",
            "brief": "Find why the nightly billing export to S3 fails with access denied.",
        },
    ).json()
    accepted = client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={
            "target": "ready",
            "reason": "Approved investigation",
            "executor_type": "workflow",
            "executor_id": "investigator",
        },
    )
    accepted.raise_for_status()
    return accepted.json()


def seed_when_ready() -> None:
    base = f"http://localhost:{os.getenv('AGENT_OS_PORT', PORT)}"
    for _ in range(60):
        try:
            if httpx.get(base + "/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    with httpx.Client(base_url=base, timeout=30) as client:
        task = create_accepted_task(client)
    print(f"\nAccepted Task ready to start from Slack: {task['id']}\n", flush=True)


# ---------------------------------------------------------------------------
# Run Super Agent Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    threading.Thread(target=seed_when_ready, daemon=True).start()
    agent_os.serve(app=app, port=PORT, reload=False)
