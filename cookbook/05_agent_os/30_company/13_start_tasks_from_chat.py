"""Start an accepted Task from a Super Agent chat and keep talking while it runs.

A person accepts the Task with an executor; Super Agent never accepts work. Asked to
start it, Super Agent submits it to the durable queue and ends its turn with the
receipt. The Task runs in its own session, so status and unrelated questions get
answers before it finishes, and the Task records which conversation asked for it.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/30_company/13_start_tasks_from_chat.py
"""

import asyncio
import os
import time
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.registry import Registry
from agno.workflow import Step, StepInput, StepOutput, Workflow
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# A deliberately slow executor
# ---------------------------------------------------------------------------
async def investigate(step_input: StepInput) -> StepOutput:
    # An awaitable wait, like real work on the network: the worker shares this process's event loop.
    await asyncio.sleep(int(os.getenv("TASK_SECONDS", "45")))
    return StepOutput(
        content="Findings: the nightly export fails because the job uses the old IAM role."
    )


db = PostgresDb(
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_chat_" + uuid4().hex[:8],
)
investigator = Workflow(
    id="investigator",
    name="Investigator",
    db=db,
    steps=[Step(name="investigate", executor=investigate)],
)
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# AgentOS with Company, Super Agent and the durable queue
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="company-chat",
    db=db,
    registry=Registry(workflows=[investigator]),
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    telemetry=False,
)


def chat(client: TestClient, message: str, session_id: str) -> str:
    started = time.monotonic()
    response = client.post(
        "/teams/superagent/runs",
        data={"message": message, "session_id": session_id, "stream": "false"},
    )
    response.raise_for_status()
    print(
        f"\n> {message}\n({time.monotonic() - started:.1f}s) {response.json().get('content')}"
    )
    return response.json().get("content") or ""


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with TestClient(agent_os.get_app()) as client:
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
        # A person accepts the Task with an executor. Super Agent does not.
        client.post(
            f"/company/tasks/{task['id']}/transitions",
            json={
                "target": "ready",
                "reason": "Approved investigation",
                "executor_type": "workflow",
                "executor_id": "investigator",
            },
        ).raise_for_status()

        session = "chat-" + uuid4().hex[:8]
        chat(client, f"Start the accepted Task {task['id']}.", session)
        chat(client, f"What is the status of Task {task['id']}?", session)
        chat(
            client,
            "Unrelated question: what is a Company Routine, in one sentence?",
            session,
        )

        print("\nWaiting for the Task to finish")
        while (current := client.get(f"/company/tasks/{task['id']}").json())[
            "status"
        ] != "in_review":
            time.sleep(3)
        started = [entry for entry in current["transitions"] if entry.get("attempt")][
            -1
        ]
        print(f"Task is {current['status']}: {current['result']['content']}")
        print(f"Requested from conversation: {started['requested_from']}")
        chat(client, f"What is the status of Task {task['id']} now?", session)
