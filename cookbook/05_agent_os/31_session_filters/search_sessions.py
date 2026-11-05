"""Search AgentOS sessions with nested AND/OR/NOT filters from the Python client.

Each search combines conditions on session fields and returns one page of
matching sessions together with the total match count.

Prerequisites: start ``server.py`` in this folder.
Run: .venvs/demo/bin/python cookbook/05_agent_os/31_session_filters/search_sessions.py
Try: change a filter, or ask for page 2 with a smaller limit.
"""

import asyncio

from agno.client import AgentOSClient

BASE_URL = "http://localhost:7779"


def eq(key: str, value: str) -> dict:
    return {"op": "EQ", "key": key, "value": value}


def show(title: str, result) -> None:
    names = [session.session_name for session in result.data]
    print(f"{title}: {result.meta.total_count} match(es) -> {names}")


# ---------------------------------------------------------------------------
# Create the Client and Search Sessions
# ---------------------------------------------------------------------------


async def search_sessions() -> None:
    client = AgentOSClient(base_url=BASE_URL)

    # One agent for one user
    result = await client.asearch_sessions(
        filter_expr={
            "op": "AND",
            "conditions": [eq("agent_id", "support"), eq("user_id", "alice")],
        }
    )
    show("Support sessions for alice", result)

    # Case-insensitive substring match on the session name
    result = await client.asearch_sessions(
        filter_expr={"op": "CONTAINS", "key": "session_name", "value": "billing"}
    )
    show("Sessions named like 'billing'", result)

    # Date range on creation time (ISO strings or epoch seconds)
    result = await client.asearch_sessions(
        filter_expr={
            "op": "AND",
            "conditions": [
                {"op": "GTE", "key": "created_at", "value": "2026-01-02T00:00:00Z"},
                {"op": "LT", "key": "created_at", "value": "2026-01-05T00:00:00Z"},
            ],
        },
        sort_order="asc",
    )
    show("Created Jan 2-4", result)

    # Negation, and scoping every condition to one user
    result = await client.asearch_sessions(
        filter_expr={
            "op": "NOT",
            "condition": {"op": "IN", "key": "agent_id", "values": ["sales"]},
        },
        user_id="bob",
    )
    show("Bob's sessions outside the sales agent", result)

    # Pagination: total_count covers every match, data holds one page
    result = await client.asearch_sessions(
        filter_expr=eq("user_id", "alice"), page=2, limit=2
    )
    show(f"Alice, page 2 of {result.meta.total_pages}", result)

    # The sync client exposes the same search
    result = client.search_sessions(filter_expr=eq("team_id", "support-team"))
    show("Support team sessions (sync)", result)


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(search_sessions())
