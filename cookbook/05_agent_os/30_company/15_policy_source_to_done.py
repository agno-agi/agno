"""One line in a Routine declaration takes its work from a Source to In review with no person.

    Routine(name="feedback-intake", instructions=..., auto_accept=True)

With auto_accept on:

1. The Routine runs on Mini Agent, reads the Source and proposes a Project and a Task.
2. The automation tick approves the Project the Routine proposed and accepts the Task.
3. The Task runs on Mini Agent, which does the work itself. It holds no run tools here.
4. Finished work waits In review. A person completes it or sends it back.

At most five of the Routine's Tasks are open at once, so the review queue is the brake.
Each automatic step is on the record with the Routine, and Super Agent reports them when
asked for the Product's status.

A named worker is one more argument, and a Task whose proposal suggests an executor runs
on that executor instead. executors limits which executors a proposal may suggest:

    auto_accept=AutoAccept(default_executor="codex-engineer")
    auto_accept=AutoAccept(default_executor="codex-engineer", executors=["writer"])

The declaration applies when the Routine is first created. After that, change it from
the UI, the API or chat. Removing auto_accept from the code does not turn it off on a
Routine that already exists.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh) and OPENAI_API_KEY.

    .venvs/demo/bin/python cookbook/05_agent_os/30_company/15_policy_source_to_done.py

The tick runs hourly by default. This example advances its due time to avoid the wait.
It serves AgentOS on a free local port, because the scheduler starts a Routine over HTTP.
The server has no authorization, so keep it local. With authorization on, a declared
auto_accept does nothing until a person turns it on for the Routine, from the UI, the
API or chat; it then runs under that person's permissions.
"""

import os
import socket
import threading
import time
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict, List
from uuid import uuid4

import httpx
import uvicorn
from agno.company import Product, Routine, Source
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager

with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    PORT = probe.getsockname()[1]
BASE_URL = f"http://127.0.0.1:{PORT}"

db = PostgresDb(
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_auto_accept_" + uuid4().hex[:8],
)
model = OpenAIResponses(id="gpt-5.6-luna")

feedback = Path(mkdtemp()) / "feedback.md"
feedback.write_text(
    "# Customer feedback\n\n"
    "- The install guide says to run `pip install agnos`. The package is `agno`, "
    "so the command fails.\n"
)

INSTRUCTIONS = (
    "Use the intake skill. Read the Product's Source. For each documentation problem a customer "
    "reports there, propose one Task with intake_product_source, with its evidence. Put the Tasks "
    "in a Project named 'Docs fixes': reuse it when it exists, propose it when it does not. Leave "
    "the executor empty. In the brief, quote the wrong text and ask the executor to write the "
    "corrected text as its deliverable. No file needs to change."
)

# ---------------------------------------------------------------------------
# The Product, its Source and its Routine, declared in code
# ---------------------------------------------------------------------------
products = [
    Product(
        id="docs",
        name="Docs",
        sources=[Source(type="markdown", reference=str(feedback))],
        routines=[
            Routine(
                name="feedback-intake", instructions=INSTRUCTIONS, auto_accept=True
            ),
        ],
    ),
]

agent_os = AgentOS(
    id="company-auto-accept",
    db=db,
    company=CompanyConfig(model=model, products=products),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db, poll_interval=0.5),
    scheduler=True,
    scheduler_poll_interval=1,
    scheduler_base_url=BASE_URL,
    telemetry=False,
)
app = agent_os.get_app()


def tasks(client: httpx.Client) -> List[Dict[str, Any]]:
    return client.get("/company/tasks", params={"product_id": "docs"}).json()["data"]


def tick() -> None:
    """Make the hourly automation tick due now."""
    schedule = db.get_schedule_by_name("Company automation")
    db.update_schedule(schedule["id"], next_run_at=0)


def wait(client: httpx.Client, done: Any, seconds: int, what: str) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        rows = tasks(client)
        if done(rows):
            return rows
        tick()
        time.sleep(3)
    raise TimeoutError(
        f"Timed out waiting for {what}: {[(row['title'], row['status']) for row in rows]}"
    )


def wait_until_healthy() -> None:
    for _ in range(60):
        try:
            if httpx.get(BASE_URL + "/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("AgentOS did not start")


def main(client: httpx.Client) -> None:
    routine = client.get("/company/routines", params={"product_id": "docs"}).json()[
        "data"
    ][0]
    print(f"Declared Routine '{routine['name']}' with auto_accept on. No person acts.")

    client.post(f"/company/routines/{routine['id']}/trigger").raise_for_status()
    print("\nRoutine triggered: Mini Agent reads the Source and proposes work")
    proposed = wait(client, lambda rows: len(rows) >= 1, 240, "a proposal")
    print(f"Proposed: {[(row['title'], row['status']) for row in proposed]}")

    finished = wait(
        client,
        lambda rows: all(row["status"] == "in_review" for row in rows),
        420,
        "the Task to reach In review",
    )
    # Nothing completes the work: a later tick leaves it In review.
    tick()
    time.sleep(5)

    for task in finished:
        task = client.get(f"/company/tasks/{task['id']}").json()
        project = client.get(f"/company/projects/{task['project_id']}").json()
        print(f"\nProject '{project['name']}' is {project['status']}")
        for entry in project["transitions"]:
            by = "auto-accept" if entry.get("auto_accept") else "a person"
            print(f"  {entry['from']} -> {entry['target']} by {by}: {entry['reason']}")
        print(
            f"Task '{task['title']}' is {task['status']} on {task['executor_type']} {task['executor_id']}"
        )
        for entry in task["transitions"]:
            by = "auto-accept" if entry.get("auto_accept") else "the run"
            print(f"  {entry['from']} -> {entry['target']} by {by}: {entry['reason']}")
        print(f"  Result: {task['result']['content'][:400]}")

        assert task["status"] == "in_review" and task["executor_id"] == "miniagent"
        decided = [entry for entry in task["transitions"] if entry.get("auto_accept")]
        assert [entry["target"] for entry in decided] == ["ready"], decided
        assert decided[0]["auto_accept"]["routine_id"] == routine["id"]
        assert decided[0]["auto_accept"]["executor_chosen_by"] == "default"
        assert [entry["target"] for entry in project["transitions"]] == ["active"]
        assert project["transitions"][0]["auto_accept"]["routine_id"] == routine["id"]
        assert not task["result"].get("invoked"), "Mini Agent holds no run tools here"

    question = "What did the Docs Product's Routine decide without a person?"
    status = client.post(
        "/teams/superagent/runs",
        data={
            "message": question,
            "session_id": "status-" + uuid4().hex[:8],
            "stream": "false",
        },
    )
    status.raise_for_status()
    print(f"\n> {question}\n{status.json().get('content')}")


if __name__ == "__main__":
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    )
    thread = threading.Thread(target=server.run)
    thread.start()
    try:
        wait_until_healthy()
        with httpx.Client(base_url=BASE_URL, timeout=180) as client:
            main(client)
    finally:
        # Let the server finish its shutdown before the interpreter exits.
        server.should_exit = True
        thread.join()
