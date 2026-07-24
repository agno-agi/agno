"""
Working State - Last-Seen Monitor
=================================

A monitor that reports change, not state: it compares current readings against
what it recorded last run in state/last-run.md, reports the difference, and
updates the file for next time.

This example runs the monitor twice; run 2 flags the one service whose latency
moved and stays quiet about the rest.
"""

import os
import time
from pathlib import Path
from typing import Dict

from agno.agent import Agent
from agno.fs import AgentFS
from agno.fs.db import DbFileSystem
from agno.models.openai import OpenAIResponses

READINGS_MONDAY = {
    "checkout-api": "210ms",
    "billing-api": "180ms",
    "search-api": "95ms",
}
READINGS_TUESDAY = {
    "checkout-api": "540ms",
    "billing-api": "185ms",
    "search-api": "96ms",
}

# ---------------------------------------------------------------------------
# Create AgentFS
# ---------------------------------------------------------------------------
Path("tmp").mkdir(exist_ok=True)
# Fresh per-run db so the demo always starts at the baseline. A real scheduled
# monitor pins one fixed, shared db_url - a new store per process forgets the
# baseline and reports nothing but baselines.
DB_FILE = os.environ.get("AGNO_FS_DB") or f"tmp/agent_fs_monitor_{int(time.time())}.db"

fs = AgentFS(
    fs=DbFileSystem(db_url=f"sqlite:///{DB_FILE}"), namespace="latency-monitor"
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions=(
        "You are a latency monitor that runs on a schedule. Each run you receive "
        "current p95 readings. Read state/last-run.md (it may not exist on the "
        "first run), report which services changed by more than 20 percent since "
        "last run - or that this is the baseline run - then overwrite "
        "state/last-run.md with the current readings using write_file, one "
        "'service: value' per line."
    ),
)


def run_monitor(readings: Dict[str, str]) -> None:
    lines = [name + ": " + value for name, value in readings.items()]
    agent.print_response("Current readings:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("run 1: no baseline yet")
    run_monitor(READINGS_MONDAY)

    print("run 2: checkout-api latency jumped - only that should be flagged")
    run_monitor(READINGS_TUESDAY)

    print("stored baseline is now:")
    print(fs.read("state/last-run.md"))
