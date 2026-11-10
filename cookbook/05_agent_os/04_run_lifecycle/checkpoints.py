"""
List and continue from AgentOS run checkpoints
==============================================

Create a run with ``checkpoint="tool-batch"``, list its persisted continuation
boundaries over HTTP, then continue from a selected ``message_index``.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/checkpoints.py
Try: Run this file with --demo in another terminal
"""

import argparse

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Checkpointing AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "checkpoint-agent"
SESSION_ID = "checkpoint-demo-session"


def get_city_fact(city: str) -> str:
    """Return a deterministic fact for a supported city."""
    facts = {
        "Kyoto": "Kyoto was Japan's imperial capital for more than one thousand years.",
        "Paris": "Paris is divided into 20 administrative arrondissements.",
    }
    return facts.get(city, f"No stored fact is available for {city}.")


db = SqliteDb(
    id="checkpoint-run-db",
    db_file="tmp/agent_os_checkpoints.db",
)

checkpoint_agent = Agent(
    id=AGENT_ID,
    name="Checkpoint Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    checkpoint="tool-batch",
    tools=[get_city_fact],
    instructions="Use get_city_fact for city facts before answering.",
)

agent_os = AgentOS(
    id="checkpoint-run-os",
    agents=[checkpoint_agent],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Create a run, list checkpoints, and continue from an interior boundary."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        run_response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": (
                    "Call get_city_fact for Paris and Kyoto, then compare the two facts "
                    "in one short paragraph."
                ),
                "stream": "false",
                "session_id": SESSION_ID,
            },
        )
        run_response.raise_for_status()
        run = run_response.json()
        run_id = run["run_id"]
        session_id = run["session_id"]
        print(f"Completed source run: {run_id}")

        checkpoints_response = client.get(
            f"/agents/{AGENT_ID}/runs/{run_id}/checkpoints",
            params={"session_id": session_id},
        )
        checkpoints_response.raise_for_status()
        checkpoints = checkpoints_response.json()["checkpoints"]

        print("Checkpoint timeline:")
        for checkpoint in checkpoints:
            print(
                f"- message_index={checkpoint['message_index']} "
                f"reason={checkpoint['reason']} status={checkpoint['status']}"
            )

        interior = [
            checkpoint for checkpoint in checkpoints if not checkpoint["is_latest"]
        ]
        if not interior:
            raise RuntimeError(
                "No tool-batch checkpoint was created. Ensure the model called get_city_fact."
            )

        message_index = interior[0]["message_index"]
        continue_response = client.post(
            f"/agents/{AGENT_ID}/runs/{run_id}/continue",
            data={
                "session_id": session_id,
                "continue_from": str(message_index),
                "input": "Continue from here, but discuss only Paris.",
                "stream": "false",
            },
        )
        continue_response.raise_for_status()
        continued = continue_response.json()

        print(f"Continued from message_index={message_index}")
        print(f"New run ID: {continued['run_id']}")
        print(f"Source run ID: {continued.get('forked_from_run_id')}")
        print(f"Result: {continued.get('content')}")


# ---------------------------------------------------------------------------
# Run Checkpoint Demo
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
        run_demo()
    else:
        agent_os.serve(app=app)
