"""Ask Super Agent for work in one message: the Task is accepted and started with no confirmation.

When a person asks for work in chat, the ask is the acceptance. Super Agent creates the Task
already accepted (Ready), with that person recorded as the one who accepted it, and starts it
in the same turn when they asked for it to be done. "Add a task to ..." creates it the same
way and leaves it Ready. Neither pauses.

A proposal is different: what Super Agent suggests on its own, and what a Routine proposes,
is still created in Backlog and accepted by a person or a policy. See
14_work_to_done_in_chat.py for that path.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and OPENAI_API_KEY.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/19_ask_and_start_in_one_message.py

The server has no authorization, so the chat user id below is the recorded accepter. With
authorization on, the person needs tasks:write and run permission on the executor, and
wiki:read to start it.
"""

import os
import time
from typing import Any, Dict, List
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from fastapi.testclient import TestClient

PERSON = "sam"

db = PostgresDb(
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_ask_" + uuid4().hex[:8],
)
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# AgentOS with Company, Super Agent and the durable queue
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="company-ask-and-start",
    db=db,
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db, poll_interval=0.5),
    telemetry=False,
)
app = agent_os.get_app()


def chat(client: TestClient, message: str, session_id: str) -> Dict[str, Any]:
    started = time.monotonic()
    response = client.post(
        "/teams/superagent/runs",
        data={
            "message": message,
            "session_id": session_id,
            "user_id": PERSON,
            "stream": "false",
        },
    )
    response.raise_for_status()
    body = response.json()
    tools = [tool.get("tool_name") for tool in body.get("tools") or []]
    print(f"\n> {message}")
    print(f"({time.monotonic() - started:.1f}s, {body.get('status')}, tools: {tools})")
    print(body.get("content"))
    return body


def tasks(client: TestClient) -> List[Dict[str, Any]]:
    return client.get("/company/tasks").json()["data"]


def wait_for(client: TestClient, task_id: str, status: str, seconds: int = 180) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        task = client.get(f"/company/tasks/{task_id}").json()
        if task["status"] == status:
            return task
        time.sleep(2)
    raise TimeoutError(f"Task did not reach {status}: it is {task['status']}")


if __name__ == "__main__":
    with TestClient(app) as client:
        # One message: the work is recorded, accepted by the person who asked, and started.
        run = chat(
            client,
            "Do this as a Task now: write release notes for version 2.4 from these changes: "
            "added streaming for workflow runs; changed the default tool call limit from 8 "
            "to 24; fixed a crash when a schedule has no timezone.",
            "chat-" + uuid4().hex[:8],
        )
        assert run["status"] != "PAUSED", "Asked work must not wait for a confirmation"
        (task,) = tasks(client)
        print(
            f"\nTask '{task['title']}' is {task['status']}, accepted by {task['accepted_by']}, "
            f"executor {task['executor_type']} {task['executor_id']}"
        )
        assert task["accepted_by"] == PERSON and task["executor_id"] == "miniagent"
        assert task["status"] in ("in_progress", "in_review")
        for entry in task["transitions"]:
            decided_by = entry.get("user_id") or entry.get("started_by") or "the run"
            print(
                f"  {entry['from']} -> {entry['target']} by {decided_by}: {entry['reason']}"
            )

        print("\nWaiting for the Task to finish")
        finished = wait_for(client, task["id"], "in_review")
        print(
            f"Task is {finished['status']}. A person reviews it; nothing completes it for them."
        )

        # "Add a task" records the work accepted and does not start it.
        run = chat(
            client,
            "Add a task to proofread the 2.4 release notes for typos.",
            "chat-" + uuid4().hex[:8],
        )
        assert run["status"] != "PAUSED"
        added = next(row for row in tasks(client) if row["id"] != task["id"])
        print(
            f"\nTask '{added['title']}' is {added['status']}, accepted by {added['accepted_by']}, "
            f"run started: {added['job_id'] is not None}"
        )
        assert added["status"] == "ready" and added["accepted_by"] == PERSON
        assert added["job_id"] is None
