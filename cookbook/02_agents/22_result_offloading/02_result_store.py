"""
The Result Store
================

`ResultStore` holds the settings and is usable without an agent: offload a
payload, read a bounded page back, search it, list a session's live result
ids, and sweep expired rows. Every method has an `a`-prefixed async twin.

Pass one to an agent to change the defaults:

    Agent(offload_tool_results=ResultStore(threshold_chars=8000, ttl_seconds=86400))

`threshold_chars` is the size at which a result is stored instead of kept
inline. The default is 16,000, one `read_result` page, so a stored result is
never cheaper to read back in one piece than it was inline. `ttl_seconds`
stamps an expiry so a sweep can reclaim old payloads; without it, results live
until the session is deleted, and deleting a session removes both the index
rows and the stored bytes.
"""

from agno.db.sqlite import SqliteDb
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
    store = ResultStore(db=db, threshold_chars=4000, ttl_seconds=7 * 86400)

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
        f"\nsearch returned {len(matches)} matches (capped at 20); first at line {matches[0].line_number}: {matches[0].line}"
    )

    # live_ids: the session's stored results, newest first, capped at 20.
    print(
        "\nlive result ids for the session:",
        [r.result_id for r in store.live_ids("demo-session")],
    )

    # Reading everything back means paging: each page names where the next one starts.
    pages, start = 0, 1
    while start is not None:
        page = store.read(ref.result_id, start_line=start)
        pages += 1
        start = page.next_start_line
    print(f"\nthe whole payload took {pages} pages of read_result")

    # Cleanup: removing the session's results deletes index rows and payloads.
    print("deleted:", store.delete_for_sessions(["demo-session"]))
    print("live ids after cleanup:", store.live_ids("demo-session"))
