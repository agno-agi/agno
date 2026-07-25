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

from datetime import date, timedelta
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

    # Age alone is not proof a record is obsolete. Deleting the oldest partition
    # just because it is oldest is how an agent silently drops history and starts
    # re-reporting items it already handled. Deletion needs a retention boundary
    # that says those records can never be needed again. Here the job declares one.
    RETENTION_DAYS = 1
    cutoff = date(2026, 7, 24) - timedelta(days=RETENTION_DAYS)
    print(
        f"recovery 2, delete only partitions older than the {RETENTION_DAYS}-day retention window:"
    )
    usage = fs.usage()
    print("  before:", usage.file_count, "files,", usage.total_bytes, "bytes")
    disposable = [
        meta.path
        for meta in fs.list("seen")
        if date.fromisoformat(meta.path.removeprefix("seen/").removesuffix(".md"))
        < cutoff
    ]
    if not disposable:
        # The honest ending when the policy clears nothing. Reaching it is a correct
        # outcome, not a failure: the caller is told storage is full and the records
        # survive. Widen the retention window only if the task really allows it.
        print("  nothing is provably obsolete: stop and report, do not evict history")
        raise SystemExit(0)
    print("  disposable under the policy:", ", ".join(disposable))
    for path in disposable:
        fs.delete(path)
    fs.append("seen/2026-07-24.md", "https://example.com/more")
    usage = fs.usage()
    print(
        "  after: ",
        usage.file_count,
        "files,",
        usage.total_bytes,
        "bytes, and the append succeeded",
    )
