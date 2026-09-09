"""
Watch and Check
===============

Run the formatter and the linter the moment a file is saved. The monitor is the
trigger; an agent holding ShellTools runs the checks, because that is where the
permission to execute anything lives.

Prerequisites: OPENAI_API_KEY and pip install agno watchfiles ruff
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/01_watch_and_check.py
Try: Run this file with --demo in another terminal
"""

import sys
import time
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.monitor import MonitorConfig, MonitorManager
from agno.os import AgentOS
from agno.tools.shell import ShellTools

# ---------------------------------------------------------------------------
# Create Checking AgentOS
# ---------------------------------------------------------------------------

WATCH_DIR = Path("tmp/checked_code")

db = SqliteDb(id="watch-and-check", db_file="tmp/watch_and_check.db")

# A monitor fires with nobody at the keyboard, so ShellTools' confirmation gate
# would just hang the run. base_dir and a narrow instruction bound it instead.
checker = Agent(
    id="checker",
    name="Checker",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[ShellTools(base_dir=WATCH_DIR)],
    instructions=[
        "Each message names the files that changed, one per line, with an absolute path.",
        "For each changed .py file run these two, passing args as a LIST of strings:",
        '  run_shell_command(args=["ruff", "format", "--check", "--no-cache", "<path>"])',
        '  run_shell_command(args=["ruff", "check", "--no-cache", "<path>"])',
        "Report what each said. Do not edit the file -- these are report-only checks.",
    ],
    db=db,
)

agent_os = AgentOS(
    name="Check On Save OS",
    agents=[checker],
    db=db,
    monitors=MonitorConfig(base_dir=str(WATCH_DIR), poll_interval=2),
)
app = agent_os.get_app()


def ensure_monitor() -> None:
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    manager = MonitorManager(db=db, base_dir=str(WATCH_DIR))
    if manager.list(status=None):
        return
    monitor = manager.create(
        name="check-on-save",
        watch_path=".",
        endpoint="/agents/checker/runs",
        payload={
            "message": "These files just changed. Run the checks.",
            "session_id": "check-session",
        },
        exclude=["*.tmp", ".ruff_cache/*", "*.pyc"],
        persistent=True,
        max_events=20,
    )
    print(f"Checking every change under {WATCH_DIR} as monitor {monitor.id}")


# ---------------------------------------------------------------------------
# Run Checking AgentOS
# ---------------------------------------------------------------------------
# The checks are report-only on purpose: a checker that rewrote the file it was
# woken for would wake itself again.


def run_demo() -> None:
    """Save a file with a lint error in it, then print what the checker said."""
    import httpx

    with httpx.Client(base_url="http://127.0.0.1:7777", timeout=30) as client:
        try:
            client.get("/health")
        except httpx.ConnectError:
            print("No AgentOS on http://127.0.0.1:7777.")
            print("Start it first, in another terminal:")
            print("    python cookbook/05_agent_os/26_monitor/01_watch_and_check.py")
            return

        # Baseline BEFORE saving, or the new event lands inside the baseline and
        # this waits for a second one that never comes.
        monitor_id = client.get("/monitors").json()["data"][0]["id"]
        seen = client.get(f"/monitors/{monitor_id}/events").json()["meta"][
            "total_count"
        ]

        target = WATCH_DIR / "messy.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Saving {target} with an unused import in it...")
        target.write_text("import os\n")

        print("Waiting for the checks to run...")
        run_id = None
        for _ in range(60):
            time.sleep(2)
            events = client.get(f"/monitors/{monitor_id}/events").json()["data"]
            if len(events) > seen and events[0]["run_id"]:
                print(f"Event: {events[0]['content']}")
                run_id = events[0]["run_id"]
                break
        if run_id is None:
            print("No event was delivered.")
            return

        for _ in range(60):
            run = client.get(
                f"/agents/checker/runs/{run_id}", params={"session_id": "check-session"}
            ).json()
            if run.get("content"):
                print("\nWhat the checker said:\n")
                print(run["content"])
                return
            time.sleep(2)
        print("The checker run did not finish in time.")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        ensure_monitor()
        agent_os.serve(app=app)
