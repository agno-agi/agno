"""
Durable Records - Radar News Delta
==================================

A scheduled news-brief agent that reports only the delta since its last run.
The seen-list is date-partitioned (one file per day under seen/), so old
partitions can be deleted without touching recent state.

This example runs the agent twice over an expanding feed: run 1 briefs
everything, run 2 briefs only the two new stories.
"""

import os
import time
from datetime import date
from pathlib import Path
from typing import List

from agno.agent import Agent
from agno.fs import AgentFS
from agno.fs.db import DbFileSystem
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
# Create AgentFS
# ---------------------------------------------------------------------------
Path("tmp").mkdir(exist_ok=True)
# Fresh per-run db so this demo starts clean on every execution. A real
# scheduled deployment pins one fixed, shared db_url instead - a new store per
# process re-reports everything, the exact bug Radar exists to fix.
DB_FILE = os.environ.get("AGNO_FS_DB") or f"tmp/agent_fs_radar_{int(time.time())}.db"

fs = AgentFS(fs=DbFileSystem(db_url=f"sqlite:///{DB_FILE}"), namespace="radar")

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


def run_radar(feed: List[str]) -> None:
    agent.print_response("Current feed:\n" + "\n".join(feed))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("run 1: everything is new")
    run_radar(FEED_MONDAY)

    print("run 2: the feed grew by two stories - the brief must cover only those")
    run_radar(FEED_TUESDAY)

    print("date-partitioned record log:")
    for meta in fs.list("seen"):
        print("  " + meta.path)
    print(fs.read(f"seen/{TODAY}.md"))
