"""Take work from a proposal to Done in a Super Agent chat, with Mini Agent doing the Task.

A person asks Super Agent to propose a Project and a Task, then decides each step in chat:
approve the Project, accept the Task, start it, and complete it after reading the result.
Each decision pauses the run. It shows the record's name, its id and what will change, and
is recorded only after the person confirms, under that person's permissions. This script
answers each confirmation as the person would in the AgentOS UI.

The Task is accepted with no executor, so it names Mini Agent. In a Task a person accepted,
Mini Agent does the work itself or runs the components that person may run. Here it runs the
Release Writer agent, and the Task records that it did.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and OPENAI_API_KEY.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/14_work_to_done_in_chat.py

The server has no authorization, so the chat user id below is the recorded decider. With
authorization on, each decision needs the caller's own grants: projects:write to approve,
tasks:write and run permission on the executor to accept, and tasks:write to complete.
"""

import json
import os
import time
from typing import Any, Dict
from uuid import uuid4

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.registry import Registry
from fastapi.testclient import TestClient

PERSON = "sam"

db = PostgresDb(
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_done_" + uuid4().hex[:8],
)
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# The component built for the job
# ---------------------------------------------------------------------------
release_writer = Agent(
    id="release-writer",
    name="Release Writer",
    description="Writes release notes from a list of changes.",
    model=model,
    db=db,
    instructions=[
        "Write release notes from the changes you are given.",
        "Use three sections: Added, Changed, Fixed. One line per change. Invent nothing.",
    ],
)

# ---------------------------------------------------------------------------
# AgentOS with Company, Super Agent and the durable queue
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="company-done-in-chat",
    db=db,
    agents=[release_writer],
    registry=Registry(agents=[release_writer]),
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db, poll_interval=0.5),
    telemetry=False,
)
app = agent_os.get_app()


def chat(client: TestClient, message: str, session_id: str) -> str:
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
    print(f"\n> {message}")
    while body.get("status") == "PAUSED":
        # A decision waits here until the person confirms it. Nothing is recorded before that.
        requirements = body["requirements"]
        for requirement in requirements:
            execution = requirement["tool_execution"]
            print(
                f"  Confirm {execution['tool_name']}: {json.dumps(execution['tool_args'])}"
            )
            requirement["confirmation"] = True
            execution["confirmed"] = True
        response = client.post(
            f"/teams/superagent/runs/{body['run_id']}/continue",
            data={
                "requirements": json.dumps(requirements),
                "session_id": session_id,
                "user_id": PERSON,
                "stream": "false",
            },
        )
        response.raise_for_status()
        body = response.json()
    tools = [tool.get("tool_name") for tool in body.get("tools") or []]
    print(f"({time.monotonic() - started:.1f}s, tools: {tools})")
    print(body.get("content"))
    return body.get("content") or ""


def only_task(client: TestClient) -> Dict[str, Any]:
    tasks = client.get("/company/tasks").json()["data"]
    assert len(tasks) == 1, f"Expected one Task, found {len(tasks)}"
    return tasks[0]


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
        session = "chat-" + uuid4().hex[:8]
        chat(
            client,
            "Create a Product named SDK. In it, propose a Project named 'Release 2.4' and one "
            "Task in that Project: write the release notes for version 2.4 from these changes: "
            "added streaming for workflow runs; changed the default tool call limit from 8 to 24; "
            "fixed a crash when a schedule has no timezone. Say in the brief that the Release "
            "Writer agent writes the notes.",
            session,
        )
        task = only_task(client)
        project = client.get(f"/company/projects/{task['project_id']}").json()
        print(f"\nRecords: Project is {project['status']}, Task is {task['status']}")
        assert (project["status"], task["status"]) == ("proposed", "backlog")

        chat(client, "Approve the Release 2.4 Project.", session)
        chat(
            client,
            "Accept the release notes Task. Name no executor, so it runs on Mini Agent.",
            session,
        )
        chat(client, "Start that Task.", session)

        print("\nWaiting for the Task to finish")
        finished = wait_for(client, task["id"], "in_review")
        print(f"Task is {finished['status']}. Components the run invoked:")
        for entry in finished["result"].get("invoked") or []:
            print(f"  {entry['type']} {entry['id']}: {entry['status']}")

        chat(client, "Show me the result of that Task.", session)
        chat(client, "Complete it. The notes read well.", session)

        done = client.get(f"/company/tasks/{task['id']}").json()
        print(
            f"\nTask is {done['status']}, executor {done['executor_type']} {done['executor_id']}"
        )
        for entry in done["transitions"]:
            decided_by = entry.get("user_id") or "the run"
            print(
                f"  {entry['from']} -> {entry['target']} by {decided_by}: {entry['reason']}"
            )
        assert done["status"] == "done" and done["executor_id"] == "miniagent"
        assert done["transitions"][-1]["user_id"] == PERSON
        ran = {entry["id"] for entry in done["result"].get("invoked") or []}
        assert "release-writer" in ran, (
            f"Mini Agent did not run the Release Writer: {ran}"
        )
