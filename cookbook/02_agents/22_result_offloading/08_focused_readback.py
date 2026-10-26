"""Find and read a small passage in a large JSON result without model calls."""

import asyncio
import json
from tempfile import TemporaryDirectory

from agno.db.sqlite import SqliteDb
from agno.offload import ResultStore

# ---------------------------------------------------------------------------
# Store a compact JSON response, as a documentation search might return
# ---------------------------------------------------------------------------
PAYLOAD = json.dumps(
    {
        "results": [
            {"content": "learning " * 25 + "background " * 2000},
            {
                "content": "learning uses saved context. AGENTIC mode saves through tools."
            },
        ]
    }
)


async def check_async(store: ResultStore, result_id: str) -> None:
    matches = await store.asearch(result_id, "learning")
    assert len(matches) == 2
    page = await store.aread(result_id, start_char=matches[1].char_offset, max_chars=80)
    assert "AGENTIC" in page.text
    assert len(page.text) <= 80
    print("Async excerpt:", page.text)


# ---------------------------------------------------------------------------
# Search first; read only the passage needed for the question
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        store = ResultStore(db=SqliteDb(db_file=f"{directory}/results.db"))
        ref = store.offload(
            session_id="focused-readback",
            run_id="example",
            tool_call_id="docs",
            tool_name="search_docs",
            tool_args={"query": "learning"},
            output=PAYLOAD,
        )
        matches = store.search(ref.result_id, "learning")
        assert len(matches) == 2
        print("Matches on the same JSON line:", len(matches))
        page = store.read(
            ref.result_id, start_char=matches[1].char_offset, max_chars=80
        )
        assert "AGENTIC" in page.text
        assert len(page.text) <= 80
        assert store.payload(ref.result_id) == PAYLOAD
        print("Sync excerpt:", page.text)
        asyncio.run(check_async(store, ref.result_id))
