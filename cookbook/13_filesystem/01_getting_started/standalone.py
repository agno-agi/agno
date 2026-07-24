"""
FileSystem - Standalone
=======================
FileSystem works without an Agent. It is the same object the agent uses,
driven from plain Python, so you get the whole API with no model and no API
keys.

This example seeds a record log, checks for exact lines with contains(), and
prints namespace usage.
"""

from uuid import uuid4

from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create FileSystem
# ---------------------------------------------------------------------------
DB_FILE = f"tmp/agent_fs_standalone_{uuid4().hex}.db"

fs = FileSystem(SqliteDb(db_file=DB_FILE))

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fs.write("notes/config.md", "focus: AI infrastructure\naudience: engineers\n")
    fs.append("seen/2026-07-24.md", "https://example.com/a\nhttps://example.com/b\n")

    print("read back the config:")
    print(fs.read("notes/config.md"))

    print("which of these records are already stored?")
    # contains() only looks inside the directory you give it. Point it at the
    # same one the appends wrote to (seen/). A mismatched directory returns
    # everything as missing, which looks just like an empty store.
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
