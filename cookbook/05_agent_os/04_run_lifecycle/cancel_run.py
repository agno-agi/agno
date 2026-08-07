"""
Cancel a background AgentOS run
===============================

Start a long non-streaming background run, cancel it through the nested run
route, and poll the database-backed run until its status becomes CANCELLED.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/cancel_run.py
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
# Create Cancellable AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "cancellable-agent"
SESSION_ID = "cancel-run-session"
TERMINAL_STATUSES = {"CANCELLED", "COMPLETED", "ERROR"}

db = SqliteDb(
    id="cancel-run-db",
    db_file="tmp/agent_os_cancel_run.db",
)

cancellable_agent = Agent(
    id=AGENT_ID,
    name="Cancellable Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Follow the requested outline carefully and write every requested section.",
)

agent_os = AgentOS(
    id="cancel-run-os",
    agents=[cancellable_agent],
)
app = agent_os.get_app()


async def poll_run(
    client: httpx.AsyncClient,
    run_id: str,
    session_id: str,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Poll one nested run route until it reaches a terminal status."""
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None

    while time.monotonic() < deadline:
        response = await client.get(
            f"/agents/{AGENT_ID}/runs/{run_id}",
            params={"session_id": session_id},
        )
        response.raise_for_status()
        run = response.json()
        if run["status"] != last_status:
            print(f"Polled status: {run['status']}")
            last_status = run["status"]
        if run["status"] in TERMINAL_STATUSES:
            return run
        await asyncio.sleep(0.25)

    raise TimeoutError(f"Run {run_id} did not stop within {timeout_seconds} seconds")


async def run_demo() -> None:
    """Start, cancel, and poll a database-backed run."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        response = await client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": (
                    "Write a detailed five-section field guide to reliable agent systems. "
                    "Use one substantial paragraph per section and stay under 500 words."
                ),
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
        print(f"Accepted: HTTP {response.status_code}, status=PENDING")
        print(f"Run ID: {run_id}")
        print(f"Session ID: {session_id}")

        cancel_response = await client.post(
            f"/agents/{AGENT_ID}/runs/{run_id}/cancel",
            params={"session_id": session_id},
        )
        cancel_response.raise_for_status()
        print(f"Cancellation accepted: HTTP {cancel_response.status_code}")

        cancelled = await poll_run(client, run_id, session_id)
        if cancelled["status"] != "CANCELLED":
            raise RuntimeError(f"Expected CANCELLED, got {cancelled['status']}")
        print("Final status: CANCELLED")


# ---------------------------------------------------------------------------
# Run Cancellation Demo
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
