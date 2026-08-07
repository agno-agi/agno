"""
Result Offloading - The store, directly
=======================================

`ResultStore` is a plain object usable without an agent: offload a payload,
read a bounded page back, search it, list a session's live result ids, and
sweep expired rows. Every method has an `a`-prefixed async twin.

`live_ids()` is the seam the post-compaction survival notice consumes: the
session's stored results, newest first, capped at 20.

`result_ttl_seconds` stamps an expiry so a sweep can reclaim old payloads;
without it, results live until the session is deleted, and deleting a session
cascades to both the index rows and the stored bytes.
"""

from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.offload import ResultStore

REPORT = "\n".join(
    f"{i:04d}: measurement {i * 3 % 17} at station {'NSEW'[i % 4]}"
    for i in range(1, 2001)
)

# ---------------------------------------------------------------------------
# Build a store
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    db = SqliteDb(db_file="tmp/offloading_store.db")
    store = ResultStore(
        FileSystem(backend=db, namespace="tool-results"),
        db=db,
        threshold=4000,
        ttl_seconds=7 * 86400,
    )

    ref = store.offload(
        session_id="demo-session",
        run_id="run-1",
        tool_call_id="call-1",
        tool_name="fetch_report",
        tool_args={"station": "all"},
        output=REPORT,
    )
    print(
        "stored:",
        ref.result_id,
        f"{ref.size_bytes} bytes,",
        f"{ref.line_count} lines,",
        ref.content_type,
    )

    # Read back a bounded page. The reply names the next start line when there is more.
    page = store.read(ref.result_id, start_line=1, end_line=5)
    print("\nfirst five lines:")
    print(page.text)
    print("next_start_line:", page.next_start_line, "| truncated:", page.truncated)

    # Search is capped at 20 matches, each line clipped.
    matches = store.search(ref.result_id, r"station N$")
    print(
        f"\nsearch found {len(matches)} matches; first at line {matches[0].line_number}: {matches[0].line}"
    )

    # live_ids: newest first, capped. This is what a compaction notice would list.
    print(
        "\nlive result ids for the session:",
        [r.result_id for r in store.live_ids("demo-session")],
    )

    # The payload round trips exactly.
    stored_bytes = store._read_payload(store.get_row(ref.result_id))
    print("round trip is byte-exact:", stored_bytes == REPORT)

    # Cleanup: removing the session's results deletes index rows and payloads.
    print("deleted:", store.delete_for_sessions(["demo-session"]))
    print("live ids after cleanup:", store.live_ids("demo-session"))
