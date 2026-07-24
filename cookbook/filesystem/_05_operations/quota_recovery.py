"""
Operations - Quota Recovery
===========================
FileSystem caps the size of every file and every namespace, and nothing is
ever evicted silently. This example hits both caps on purpose, shows the
guidance the agent gets back, and then recovers the way that guidance
suggests, by starting a new partition and deleting old ones.

The caps are set very small here so the numbers stay readable. No model, no
API keys.
"""

from uuid import uuid4

from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.errors import QuotaExceededError

# ---------------------------------------------------------------------------
# Create FileSystem - deliberately tiny caps
# ---------------------------------------------------------------------------
# A fresh store per run. This example fills a namespace to its cap, so a reused
# store would already be full the second time. The uuid suffix keeps the file
# distinct even for two runs started in the same second.
DB_FILE = f"tmp/agent_fs_quota_{uuid4().hex}.db"

fs = FileSystem(
    SqliteDb(db_file=DB_FILE),
    namespace="radar",
    max_file_bytes=200,
    max_namespace_bytes=300,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("fill one partition to its per-file cap:")
    fs.append(
        "seen/2026-07-22.md", "\n".join(f"https://example.com/{i}" for i in range(8))
    )
    try:
        fs.append("seen/2026-07-22.md", "https://example.com/one-too-many")
    except QuotaExceededError as e:
        print("  typed error:", e.scope, e.current, ">", e.limit)

    print("the agent would see the same refusal as a tool string:")
    toolkit = fs.tools()
    print(
        "  "
        + toolkit.append_file("seen/2026-07-22.md", "https://example.com/one-too-many")
    )

    print("recovery 1, start a new partition (the error suggests date partitioning):")
    fs.append("seen/2026-07-23.md", "https://example.com/one-too-many")
    print("  wrote to seen/2026-07-23.md")

    print("fill the namespace to its cap:")
    try:
        while True:
            fs.append("seen/2026-07-24.md", "https://example.com/more")
    except QuotaExceededError as e:
        print("  typed error:", e.scope, e.current, "of", e.limit)
    print("  " + toolkit.append_file("seen/2026-07-24.md", "https://example.com/more"))

    print("recovery 2, delete the oldest partition, then retry:")
    usage = fs.usage()
    print("  before:", usage.file_count, "files,", usage.total_bytes, "bytes")
    fs.delete("seen/2026-07-22.md")
    fs.append("seen/2026-07-24.md", "https://example.com/more")
    usage = fs.usage()
    print(
        "  after: ",
        usage.file_count,
        "files,",
        usage.total_bytes,
        "bytes, and the append succeeded",
    )
