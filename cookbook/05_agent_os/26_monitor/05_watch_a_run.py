"""
Watch a Run
===========

Follow a run that is already executing and get pinged when it finishes. No
command, no files: the monitor polls the run and emits one event when it ends.

Prerequisites: OPENAI_API_KEY and pip install agno
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/05_watch_a_run.py
Try: Run this file with --demo in another terminal
"""

import sys
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Run-Watching AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(id="monitor-run-watch", db_file="tmp/monitor_run_watch.db")

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=["Answer thoroughly but concisely."],
    db=db,
)

# Pinged with the finished run's output as its message.
notifier = Agent(
    id="notifier",
    name="Notifier",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You are pinged when a run finishes. Say in one sentence what it produced."
    ],
    db=db,
)

# A run watch reads the runs table directly, so it needs no watch_commands and
# no base_dir -- it runs nothing.
agent_os = AgentOS(
    name="Run Watch OS",
    agents=[researcher, notifier],
    db=db,
    monitors=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Run-Watching AgentOS
# ---------------------------------------------------------------------------
# A run that ends in ERROR or CANCELLED still fires the event and marks the
# monitor failed, so a watch that worked is never confused with a run that did not.


def run_demo() -> None:
    """Start a background run, watch it, and print what the notifier was told."""
    import httpx

    with httpx.Client(base_url="http://127.0.0.1:7777", timeout=60) as client:
        try:
            client.get("/health")
        except httpx.ConnectError:
            print("No AgentOS on http://127.0.0.1:7777.")
            print("Start it first, in another terminal:")
            print("    python cookbook/05_agent_os/26_monitor/05_watch_a_run.py")
            return

        print("Starting a background run...")
        started = client.post(
            "/agents/researcher/runs",
            data={
                "message": "Name three deep-sea creatures.",
                "background": "true",
                "stream": "false",
                "session_id": "demo",
            },
        ).json()
        run_id = started["run_id"]
        print(f"  run_id: {run_id}")

        created = client.post(
            "/monitors",
            json={
                "name": f"watch-{run_id[:8]}",
                "watch_run_id": run_id,
                "endpoint": "/agents/notifier/runs",
                "timeout_seconds": 300,
            },
        ).json()
        print(f"Watching it as monitor {created['id']}")

        print("Waiting for the run to finish...")
        for _ in range(60):
            time.sleep(2)
            events = client.get(f"/monitors/{created['id']}/events").json()["data"]
            if events:
                print("\nWhat the watch caught:\n")
                print(events[0]["content"])
                return
        print("The run never settled within the deadline.")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        agent_os.serve(app=app)
