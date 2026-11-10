"""Start an accepted Task from a Super Agent chat and keep talking while it runs.

A person accepts the Task with an executor; Super Agent never accepts work. Asked to
start it, Super Agent submits it to the durable queue and ends its turn with the
receipt. The Task runs in its own session, so status and unrelated questions get
answers before it finishes, and the Task records which conversation asked for it.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and OPENAI_API_KEY.

Scripted run (no UI): starts the Task, asks its status and an unrelated question while
it runs, then waits for the result and prints how long each reply took.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/13_start_tasks_from_chat.py

Try it in the AgentOS UI: serve on http://localhost:7777 with one accepted Task seeded.
The seeded Task id is printed once the server is up.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/13_start_tasks_from_chat.py --serve

    1. Connect the AgentOS UI (os.agno.com or a local agno-os) to http://localhost:7777.
    2. In Super Agent chat, ask "Start the task <seeded id>". The reply is a receipt.
    3. While it runs, ask "What's the status of that task?" and any unrelated question;
       both answer without waiting for the Task.
    4. After about 90 seconds, ask for the status again: finished and waiting for review.
       The Task's latest attempt in the Company view shows the chat in requested_from.

The server has no authorization, so keep it local. AgentOS.serve prefers AGENT_OS_PORT
over the port below; unset it, or connect to the port it names. TASK_SECONDS sets how
long the executor takes.
"""

import asyncio
import os
import sys
import threading
import time
from typing import Any, Dict
from uuid import uuid4

import httpx
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.registry import Registry
from agno.workflow import Step, StepInput, StepOutput, Workflow
from fastapi.testclient import TestClient

SERVE = "--serve" in sys.argv
PORT = 7777


# ---------------------------------------------------------------------------
# A deliberately slow executor
# ---------------------------------------------------------------------------
async def investigate(step_input: StepInput) -> StepOutput:
    # Await rather than block: the queue worker shares this process's event loop with chat.
    await asyncio.sleep(int(os.getenv("TASK_SECONDS", "90" if SERVE else "45")))
    return StepOutput(
        content="Findings: the nightly export fails because the job uses the old IAM role."
    )


db = PostgresDb(
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    # The served demo keeps its records between restarts; each scripted run starts clean.
    db_schema="company_chat" if SERVE else "company_chat_" + uuid4().hex[:8],
)
investigator = Workflow(
    id="investigator",
    name="Investigator",
    description="Slow investigation executor for starting Tasks from chat.",
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
    workflows=[investigator],
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    telemetry=False,
)
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
    # A person accepts the Task with an executor. Super Agent does not.
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


# ---------------------------------------------------------------------------
# Scripted run
# ---------------------------------------------------------------------------
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


def scripted() -> None:
    with TestClient(app) as client:
        task = create_accepted_task(client)
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


# ---------------------------------------------------------------------------
# Served for the AgentOS UI
# ---------------------------------------------------------------------------
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
    print(f"\nAccepted Task ready to start from chat: {task['id']}\n", flush=True)


if __name__ == "__main__":
    if SERVE:
        threading.Thread(target=seed_when_ready, daemon=True).start()
        agent_os.serve(app=app, port=PORT, reload=False)
    else:
        scripted()
