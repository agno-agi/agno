"""Get a Task's result with its evidence, answer its question, and continue the same work.

A worker investigates and stops at a decision: it reports what it found, what it checked
and the one question a person must answer. The Task records the reply and the commands
and tools the worker actually ran. The person's answer continues the same Task on the
same worker session, so the worker builds on its earlier turn instead of starting over.
Super Agent never answers for the person and never accepts or completes the Task.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and OPENAI_API_KEY.

Scripted run (no UI): start the Task from chat, wait for its result, ask Super Agent for
an update, answer the worker's question, and wait for the continued result.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/14_continue_tasks_from_chat.py

Try it in the AgentOS UI: serve on http://localhost:7777 with one accepted Task seeded.
The seeded Task id is printed once the server is up.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/14_continue_tasks_from_chat.py --serve

    1. Connect the AgentOS UI (os.agno.com or a local agno-os) to http://localhost:7777.
    2. In Super Agent chat, ask "Start the task <seeded id>".
    3. Watch the Task change without asking: in a terminal, stream its events with
       curl -N "http://localhost:7777/company/events?task_id=<seeded id>"
    4. When it is waiting for review, ask Super Agent what it found. The reply includes the
       evidence the worker recorded and its question.
    5. Answer in chat, for example "Go with option A". The Task continues on the same session,
       and its new attempt records your reply.

The server has no authorization, so keep it local. AgentOS.serve prefers AGENT_OS_PORT
over the port below; unset it, or connect to the port it names.
"""

import os
import sys
import threading
import time
from typing import Any, Dict
from uuid import uuid4

import httpx
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from fastapi.testclient import TestClient

SERVE = "--serve" in sys.argv
PORT = 7777


# ---------------------------------------------------------------------------
# The worker's tools: what it runs is recorded as evidence on the Task
# ---------------------------------------------------------------------------
def read_export_logs() -> str:
    """Read the last nightly billing export log."""
    return (
        "02:00:01 export started role=arn:aws:iam::123:role/billing-export-old\n"
        "02:00:03 PutObject s3://billing-exports/2026-11-10.csv AccessDenied\n"
        "02:00:03 export failed"
    )


def list_iam_roles() -> str:
    """List the IAM roles that can write billing exports."""
    return "billing-export-new: s3:PutObject on billing-exports (created 2026-11-09)\nbilling-export-old: deleted policy"


def set_export_role(role: str) -> str:
    """Set the IAM role the nightly billing export runs as. Use only after a person decides."""
    return f"nightly-export config updated: role=arn:aws:iam::123:role/{role}; dry-run PutObject -> 200 OK"


db = PostgresDb(
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    # The served demo keeps its records between restarts; each scripted run starts clean.
    db_schema="company_continue" if SERVE else "company_continue_" + uuid4().hex[:8],
)
model = OpenAIResponses(id="gpt-5.6-luna")
investigator = Agent(
    id="investigator",
    name="Investigator",
    model=model,
    db=db,
    tools=[read_export_logs, list_iam_roles, set_export_role],
    instructions=[
        "Investigate with your tools before concluding, and say which checks you ran.",
        "Change nothing until a person decides. When a fix needs a decision, give two options, recommend one and"
        " ask which to apply.",
        "When the input has a follow_up, it is the person's answer to your previous result: act on it.",
    ],
    telemetry=False,
)

# ---------------------------------------------------------------------------
# AgentOS with Company, Super Agent and the durable queue
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="company-continue",
    db=db,
    agents=[investigator],
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    telemetry=False,
)
app = agent_os.get_app()


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
            "executor_type": "agent",
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
    content = response.json().get("content") or ""
    print(f"\n> {message}\n({time.monotonic() - started:.1f}s) {content}")
    return content


def wait_for_review(client: TestClient, task_id: str, attempt: int) -> Dict[str, Any]:
    while True:
        task = client.get(f"/company/tasks/{task_id}").json()
        attempts = [entry for entry in task["transitions"] if entry.get("attempt")]
        if task["status"] == "in_review" and attempts[-1]["attempt"] == attempt:
            return task
        time.sleep(3)


def show(task: Dict[str, Any]) -> None:
    result = task["result"]
    print(f"\nAttempt result ({result['status']}): {result['content']}")
    for item in result.get("evidence") or []:
        print(
            f"  evidence: {item['kind']} {item['name']} -> {str(item.get('output'))[:80]!r}"
        )
    if result.get("evidence_note"):
        print(f"  {result['evidence_note']}")


def scripted() -> None:
    with TestClient(app) as client:
        task = create_accepted_task(client)
        session = "chat-" + uuid4().hex[:8]
        chat(client, f"Start the accepted Task {task['id']}.", session)

        first = wait_for_review(client, task["id"], 1)
        show(first)
        chat(client, "Any update on the export Task I started?", session)
        chat(
            client, f"For Task {task['id']}: go with your recommended option.", session
        )

        second = wait_for_review(client, task["id"], 2)
        show(second)
        entry = [entry for entry in second["transitions"] if entry.get("attempt")][-1]
        print(f"\nAttempt 2 continued from: {entry['follow_up']}")
        print(
            f"Same worker session across attempts: {second['session_id'] == first['session_id']}"
        )


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
