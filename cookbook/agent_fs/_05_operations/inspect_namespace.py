"""
Operations - Inspect a Namespace
================================

An agent's file store is reachable from any script: construct AgentFS with the
same backend and namespace name, and you hold the same files the agent holds.
Inspect, read, and seed - no Agent, no model, no server.

This example seeds records a scheduled agent will dedupe against on its next
run, which is how you backfill "already processed" state before first launch.
"""

import os
import time
from pathlib import Path

from agno.fs import AgentFS
from agno.fs.db import DbFileSystem
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create AgentFS - the same backend and namespace the agent uses
# ---------------------------------------------------------------------------
Path("tmp").mkdir(exist_ok=True)
DB_FILE = os.environ.get("AGNO_FS_DB") or f"tmp/agent_fs_inspect_{int(time.time())}.db"

fs = AgentFS(fs=DbFileSystem(db_url=f"sqlite:///{DB_FILE}"), namespace="radar")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Stand in for a live agent's history (normally already in the table).
    fs.write("state/last-run.md", "2026-07-23: briefed 3 stories\n")
    fs.append("seen/2026-07-23.md", "acme-ships-vector-db\nmeridian-raises-b\n")

    print("what does this agent have?")
    for meta in fs.list():
        print(f"  {meta.path}  {meta.size_bytes}B  v{meta.version}")
    usage = fs.usage()
    pprint({"files": usage.file_count, "bytes": usage.total_bytes})

    print("read its working state:")
    print("  " + str(fs.read("state/last-run.md")).strip())

    print("seed records it should treat as already processed:")
    fs.append("seen/2026-07-23.md", "kite-os-release\nnimbus-gpu-cloud\n")
    result = fs.contains(["kite-os-release", "brand-new-story"], directory="seen")
    pprint({"found": result.found, "missing": result.missing})

    print("an agent that checks directory='seen' will now skip everything in 'found'.")
