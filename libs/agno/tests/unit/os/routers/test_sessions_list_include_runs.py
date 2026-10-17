"""AgentOS list views must not load session runs into memory.

`get_sessions_page` backs `GET /sessions` and the MCP `get_sessions` tool, and
both render `SessionSchema` objects, which have no `runs` field. The db layer
defaults to `include_runs=True`, so the service has to opt out explicitly or
every list call deserializes full run payloads only to discard them.
"""

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.os.services.sessions import get_sessions_page


async def test_get_sessions_page_requests_no_runs():
    db = InMemoryDb()
    calls: list[dict] = []

    original = db.get_sessions

    def recording_get_sessions(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    db.get_sessions = recording_get_sessions  # type: ignore[method-assign]

    sessions, total_count = await get_sessions_page(db, limit=10, page=1)

    assert total_count == 0
    assert sessions == []
    assert calls, "get_sessions_page must call db.get_sessions"
    assert calls[0]["include_runs"] is False
    assert calls[0]["deserialize"] is False
