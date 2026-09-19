"""
Custom Store Settings
=====================

`offload_tool_results=True` uses the defaults: results longer than 16,000
characters are stored, the envelope previews 20 lines or 1,200 characters,
and payloads live until the session is deleted.

A `ResultStore` is the settings object for everything else:

    ResultStore(
        threshold_chars=16000,  # store results longer than this
        preview_lines=20,       # the envelope shows this many lines ...
        preview_chars=1200,     # ... or this many characters, whichever is less
        ttl_seconds=None,       # expiry; a sweep reclaims expired payloads
        member_responses=True,  # teams only: also envelope stored member runs
        db=None,                # defaults to the agent's db
        fs=None,                # a FileSystem for payloads; defaults to AgentFS on db
    )

The object you pass is never modified. It is bound to the agent's database as
a copy, and that copy is `agent.result_store`, so one settings object can
configure several agents.

This example lowers the threshold and the preview, sets a one-hour lifetime,
and then runs the expiry sweep as if an hour had passed.
"""

import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.offload import ResultStore

db = SqliteDb(db_file="tmp/custom_store_settings.db")

INVENTORY = "\n".join(
    f"bin {i:04d}: {(i * 13) % 97} units of item-{i % 53}" for i in range(1, 401)
)


def count_inventory() -> str:
    """Count every bin in the warehouse.

    Returns:
        str: One bin per line.
    """
    return INVENTORY


# The settings object. Nothing here is tied to one agent.
settings = ResultStore(
    threshold_chars=4000,
    preview_lines=3,
    preview_chars=200,
    ttl_seconds=3600,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[count_inventory],
    offload_tool_results=settings,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "custom-store-settings"
    output = agent.run(
        "How many units of item-7 are there in total across all bins? Use search_result.",
        session_id=session_id,
    )
    print(output.content)

    print("\nThe envelope with a 3-line / 200-character preview:")
    for message in output.messages or []:
        if message.role == "tool" and message.tool_name == "count_inventory":
            print(message.content)

    store = agent.result_store
    print("\nThe live store is a bound copy of the settings:")
    print(f"   agent.result_store is settings: {store is settings}")
    print(
        f"   threshold: {store.threshold_chars}, ttl: {store.ttl_seconds}s, db bound: {store.db is db}"
    )

    refs = store.live_ids(session_id)
    print(f"\nStored results for the session: {[r.result_id for r in refs]}")
    row = store.get_row(refs[0].result_id)
    print(
        f"   created_at={row['created_at']} expires_at={row['expires_at']} ({row['expires_at'] - row['created_at']}s later)"
    )

    # Payloads are swept when they expire. The sweep runs on its own at most
    # every five minutes on a write; here it is run by hand, as if an hour
    # and a minute had passed.
    swept = store.sweep_expired(now=int(time.time()) + 3660)
    print(
        f"\nSwept {swept} expired result(s); live ids now: {[r.result_id for r in store.live_ids(session_id)]}"
    )
