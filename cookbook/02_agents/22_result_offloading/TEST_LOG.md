# Test Log

Tested 2026-08-20 against `gpt-5.5` (OpenAIResponses), SQLite, with the worktree's Python (agno from this branch).

### 01_offload_tool_results.py

**Status:** PASS

**Description:** An agent with `offload_tool_results=True` over SqliteDb whose `fetch_catalog` tool returns a 4,000-row, 146,300-character table. The agent was asked which warehouse SKU-00042 is in and how many rows the catalog has, and told to use `search_result` rather than re-fetching.

**Result:** The tool result was replaced in the transcript by a 920-character envelope (`lines="4000" size="142.9KB"`). The model called `search_result` with `^SKU-00042\b`, got one match (`42: SKU-00042 part-5 qty=21 warehouse=C`), and answered warehouse C and 4,000 rows. Both are correct (42 mod 5 = 2 selects C; the catalog is 4,000 lines). Per-call input tokens stayed under 1,000 on every turn, so the 143KB result never re-entered the context. Two consecutive runs gave identical results; no warnings, no traceback.

---

### 02_result_store.py

**Status:** PASS

**Description:** `ResultStore` used directly, without an agent: offload a 2,000-line report with `threshold_chars=4000` and a 7-day TTL, read lines 1-5, search `station N$`, list the session's live ids, page through the whole payload, and delete the session's results.

**Result:** Stored 66,823 bytes, 2,000 lines as text. The first page returned lines 1-5 with `next_start_line: 6`. The search returned 20 matches, the cap, the first at line 4. `live_ids` listed the one result. Reading the whole payload took 5 pages of `read_result`. `delete_for_sessions` returned 1 and `live_ids` was empty afterwards. No warnings, no traceback.

---
