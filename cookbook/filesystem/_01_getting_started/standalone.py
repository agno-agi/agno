"""
FileSystem - Standalone
====================

FileSystem is a complete durable-filesystem API without any Agent: the same
object an agent uses, driven from plain Python. No model, no API keys.

This example seeds a record log, proves exact-line dedupe with contains(),
and prints namespace usage.
"""

import os
import time
from pathlib import Path

from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
Path("tmp").mkdir(exist_ok=True)
DB_FILE = (
    os.environ.get("AGNO_FS_DB") or f"tmp/agent_fs_standalone_{int(time.time())}.db"
)

fs = FileSystem(backend=DbFileSystem(db_url=f"sqlite:///{DB_FILE}"), namespace="radar")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fs.write("notes/config.md", "focus: AI infrastructure\naudience: engineers\n")
    fs.append("seen/2026-07-24.md", "https://example.com/a\nhttps://example.com/b\n")

    print("read back the config:")
    print(fs.read("notes/config.md"))

    print("which of these records are already stored?")
    # Check against the same directory the appends wrote to (seen/): a
    # mismatched scope reads exactly like a fresh, empty store.
    result = fs.contains(
        ["https://example.com/a", "https://example.com/c"], directory="seen"
    )
    pprint({"found": result.found, "missing": result.missing})

    print("record the missing one, then check again:")
    fs.append("seen/2026-07-24.md", "https://example.com/c\n")
    result = fs.contains(["https://example.com/c"], directory="seen")
    pprint({"found": result.found, "missing": result.missing})

    print("files and usage:")
    pprint([m.path for m in fs.list()])
    usage = fs.usage()
    pprint({"files": usage.file_count, "bytes": usage.total_bytes})
