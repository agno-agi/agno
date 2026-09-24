"""
Operations - Inspect and Seed Files
===================================
An agent's files are reachable from any script. Point FileSystem at the same
backend and you hold the same files the agent holds, so you can inspect, read
and seed them with no Agent, model or server. (If the agent names a namespace,
pass the same one here.)

This example seeds records that a scheduled agent will dedupe against on its
next run. That is how you backfill "already processed" state before a first
launch.
"""

from uuid import uuid4

from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create FileSystem - the same backend and namespace the agent uses
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_inspect_{uuid4().hex}.db"

fs = FileSystem(SqliteDb(db_file=DB_FILE))

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
