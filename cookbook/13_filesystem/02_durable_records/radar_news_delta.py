"""
Durable Records - Radar News Delta
==================================
A scheduled news-brief agent that reports only what is new since its last
run. The seen-list is date-partitioned, one file per day under seen/, so you
can delete old partitions without touching recent state.

This example runs the agent twice over a growing feed. Run 1 briefs
everything, run 2 briefs only the two new stories.
"""

from datetime import date
from typing import List
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Inlined feed (a real Radar would fetch these)
# ---------------------------------------------------------------------------
FEED_MONDAY = [
    "acme-ships-vector-db|Acme ships a managed vector database",
    "meridian-raises-b|Meridian raises a 120M Series B for agent infra",
    "kite-os-release|Kite releases an open-source agent runtime",
]
FEED_TUESDAY = FEED_MONDAY + [
    "acme-adds-hybrid-search|Acme adds hybrid search to its vector db",
    "nimbus-gpu-cloud|Nimbus launches a spot-GPU cloud for fine-tuning",
]

TODAY = date.today().isoformat()

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
# Fresh per-run db so this demo starts clean on every execution. A real
# scheduled deployment pins one fixed, shared database. With a new store per
# process it would re-report every story it has already briefed.
DB_FILE = f"tmp/agent_fs_radar_{uuid4().hex}.db"

fs = FileSystem(SqliteDb(db_file=DB_FILE))

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[fs.tools()],
    instructions=(
        "You are Radar, a news-brief agent that runs on a schedule. Each run you "
        "receive the current feed as 'id|headline' lines. Report ONLY stories you "
        "have never reported before: call check_lines on the ids with "
        "directory='seen' first, brief the missing ones (one bullet each), then "
        f"record the newly reported ids with append_file to seen/{TODAY}.md, one "
        "id per line. If nothing is new, say so."
    ),
)


def run_radar(feed: List[str], session_id: str) -> None:
    # A distinct session_id per run, matching a scheduled agent that gets a fresh
    # session every time. Nothing carries over in session state, so the delta can
    # only come from the durable filesystem.
    agent.print_response("Current feed:\n" + "\n".join(feed), session_id=session_id)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("run 1 (session radar-monday): everything is new")
    run_radar(FEED_MONDAY, session_id="radar-monday")

    print(
        "run 2 (session radar-tuesday, fresh session): the feed grew by two, so brief only those"
    )
    run_radar(FEED_TUESDAY, session_id="radar-tuesday")

    print("date-partitioned record log:")
    for meta in fs.list("seen"):
        print("  " + meta.path)
    print(fs.read(f"seen/{TODAY}.md"))
