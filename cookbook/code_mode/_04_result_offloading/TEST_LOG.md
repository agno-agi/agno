# Test Log - _04_result_offloading

Tested 2026-08-08 against `gpt-5.5` (OpenAIResponses), agno 3.0.0a1, on `.venvs/demo`.

### basic.py

**Status:** PASS

**Description:** An agent with `offload_tool_results=True` over SqliteDb whose `fetch_catalog` tool returns a 4000-row, 146,300-character table. The agent was asked which warehouse SKU-00042 is in and how many rows the catalog has, and told to use `search_result` rather than re-fetching.

**Result:** Correct answer — "SKU-00042 is in warehouse C. The catalog has 4,000 rows." — both verified against the fixture. The tool message in the transcript was **920 characters** where the full result was 146,300: an envelope reading `<result id="res_581f295f7a" tool="fetch_catalog" lines="4000" size="142.9KB">` followed by the first rows and the read instructions. The model used `search_result` to find the SKU rather than re-running the tool.

---

### with_ttl_and_store.py

**Status:** PASS

**Description:** `ResultStore` used directly without an agent: offload a 2000-line report, read a bounded page, search, list live ids, verify the round trip, and cascade-delete.

**Result:** Stored as `res_72a55667cc`, 66,823 bytes, 2000 lines, content type `text`. `read(start_line=1, end_line=5)` returned exactly the first five lines with `next_start_line=6` and `truncated=False`. `search(r"station N$")` stopped at the 20-match cap with the first at line 4. `live_ids()` returned the single id. The byte-exactness check (`stored == REPORT`) returned **True** — the round trip is lossless. `delete_for_sessions` removed 1 result and `live_ids` then returned empty, confirming both the index row and the payload were cleaned up.
