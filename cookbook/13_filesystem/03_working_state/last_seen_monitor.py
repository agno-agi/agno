"""
Working State - Last-Seen Monitor
=================================
A monitor that reports what changed rather than what the current values are.
It compares the readings it is given against what it recorded last run in
state/last-run.md, reports the difference, and overwrites the file for next
time.

This example runs the monitor twice. Run 2 flags the one service whose
latency moved and stays quiet about the rest.
"""

from typing import Dict
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
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
# Create FileSystem
# ---------------------------------------------------------------------------
# Fresh per-run db so the demo always starts at the baseline. A real scheduled
# monitor pins one fixed, shared database. With a new store per process it would
# forget the baseline and report nothing but baselines.
DB_FILE = f"tmp/agent_fs_monitor_{uuid4().hex}.db"

fs = FileSystem(SqliteDb(db_file=DB_FILE))

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions=(
        "You are a latency monitor that runs on a schedule. Each run you receive "
        "current p95 readings. Read state/last-run.md (it may not exist on the "
        "first run), then report which services changed by more than 20 percent "
        "since last run, or say that this is the baseline run. Finally overwrite "
        "state/last-run.md with the current readings using write_file, one "
        "'service: value' per line."
    ),
)


def run_monitor(readings: Dict[str, str], session_id: str) -> None:
    # A distinct session per run, like a scheduled monitor gets. Nothing carries in
    # session state, so the comparison can only come from the stored baseline.
    lines = [name + ": " + value for name, value in readings.items()]
    agent.print_response(
        "Current readings:\n" + "\n".join(lines), session_id=session_id
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("run 1: no baseline yet")
    run_monitor(READINGS_MONDAY, session_id="monitor-monday")

    print("run 2: checkout-api latency jumped, so only that should be flagged")
    run_monitor(READINGS_TUESDAY, session_id="monitor-tuesday")

    print("stored baseline is now:")
    print(fs.read("state/last-run.md"))
