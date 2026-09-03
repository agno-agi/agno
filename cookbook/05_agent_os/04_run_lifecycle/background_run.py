"""
Run an AgentOS request in the background
=========================================

Submit a non-streaming background run, observe the HTTP 202/PENDING contract,
then poll the persisted run until it reaches a terminal status.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/background_run.py
Try: Run this file with --demo in another terminal
"""

import argparse
import asyncio
import time
from typing import Any

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Background Run AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "background-run-agent"
SESSION_ID = "background-run-session"
TERMINAL_STATUSES = {"CANCELLED", "COMPLETED", "ERROR"}

db = SqliteDb(
    id="background-run-db",
    db_file="tmp/agent_os_background_run.db",
)

background_run_agent = Agent(
    id=AGENT_ID,
    name="Background Run Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer clearly and keep the final response under three paragraphs.",
)

agent_os = AgentOS(
    id="background-run-os",
    agents=[background_run_agent],
)
app = agent_os.get_app()


async def poll_run(
    client: httpx.AsyncClient,
    run_id: str,
    session_id: str,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Poll one nested run route until the run reaches a terminal status."""
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None

    while time.monotonic() < deadline:
        response = await client.get(
            f"/agents/{AGENT_ID}/runs/{run_id}",
            params={"session_id": session_id},
        )
        response.raise_for_status()
        run = response.json()
        status = run["status"]

        if status != last_status:
            print(f"Run status: {status}")
            last_status = status
        if status in TERMINAL_STATUSES:
            return run

        await asyncio.sleep(0.5)

    raise TimeoutError(f"Run {run_id} did not finish within {timeout_seconds} seconds")


async def run_demo() -> None:
    """Submit a background run and poll its persisted state."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        response = await client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Explain why persisted background runs are useful.",
                "background": "true",
                "stream": "false",
                "session_id": SESSION_ID,
            },
        )
        if response.status_code != 202:
            raise RuntimeError(
                f"Expected HTTP 202 for a background run, got {response.status_code}: {response.text}"
            )

        accepted = response.json()
        if accepted["status"] != "PENDING":
            raise RuntimeError(
                f"Expected initial PENDING status, got {accepted['status']}"
            )

        run_id = accepted["run_id"]
        session_id = accepted["session_id"]
        print(f"Accepted: HTTP {response.status_code}")
        print(f"Run ID: {run_id}")
        print(f"Session ID: {session_id}")
        print("Run status: PENDING")

        completed = await poll_run(client, run_id, session_id)
        if completed["status"] != "COMPLETED":
            raise RuntimeError(f"Background run ended with {completed['status']}")
        print(f"Result: {completed.get('content')}")


# ---------------------------------------------------------------------------
# Run Background Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Call an AgentOS server already running at http://localhost:7777.",
    )
    args = parser.parse_args()

    if args.demo:
        asyncio.run(run_demo())
    else:
        agent_os.serve(app=app)
