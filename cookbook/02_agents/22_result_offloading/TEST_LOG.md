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

Tested 2026-08-21 against `gpt-5.5` (OpenAIResponses), SQLite and PostgreSQL (pgvector container on 5532), with the branch's Python.

### 03_where_results_live.py

**Status:** PASS

**Description:** One agent whose `read_access_log` tool returns 1,500 lines (87,223 characters), with a tool hook recording the size it sees. After the run the example opens the three places the result went: the stored session run, the `agno_tool_results` index row, and the AgentFS payload, then counts all three with plain SQL.

**Result:** The model found the one 500 (`GET /api/orders/777`) via `search_result`. The stored tool message and `RunOutput.tools[0].result` were the 1,315-character envelope; the tool hook saw all 87,223 characters. The index row showed `namespace=tool-results/where-results-live-ec946760`, `path=results/<run_id>/res_1f66b7d105.txt`, 87,223 bytes, 1,500 lines. `FileSystem(backend=db, namespace=...).read(path)` returned a payload identical to the tool output. SQL counts: 1 session row, 1 index row, 1 `agno_fs` row of 87,223 bytes. No warnings, no traceback.

---

### 04_custom_store_settings.py

**Status:** PASS

**Description:** `ResultStore(threshold_chars=4000, preview_lines=3, preview_chars=200, ttl_seconds=3600)` on an agent whose tool returns an 11.6KB inventory; then the bound copy on `agent.result_store`, the index row's expiry, and a manual `sweep_expired` as if an hour had passed.

**Result:** The model answered 329 units of item-7 (verified: the sum over bins with `i % 53 == 7` is 329). The envelope previewed exactly three lines. `agent.result_store is settings` printed False with threshold 4000, ttl 3600 and the db bound; `expires_at - created_at` was 3600. The sweep with `now` one hour and a minute ahead removed 1 result and `live_ids` was empty afterwards. No warnings, no traceback.

---

### 05_payloads_on_disk.py

**Status:** PASS

**Description:** `ResultStore(fs=FileSystem(backend=LocalFileSystem(root="tmp/offloaded_payloads")))` so payloads go to a local directory while the index stays on SQLite; lists the files, then deletes the session.

**Result:** The model answered 400 cold-storage rows (every third of 1,200). The index row pointed at `tool-results/payloads-on-disk-.../results/<run_id>/res_985546ab42.txt` and a 35,599-byte file appeared under `tmp/offloaded_payloads/tool-results%2fpayloads-on-disk-.../results/<run_id>/`. `delete_session` removed the index row and the file (`(no files)`). No warnings, no traceback.

---

### 06_postgres_layout.py

**Status:** PASS

**Description:** The same agent against `PostgresDb(db_schema="ai")`; then SQL over `ai.agno_tool_results` and `fs.agno_fs`, the stored run via the db API, and the delete cascade.

**Result:** The model answered 75 remote sales employees (every 20th of 1,500). The index row appeared in `ai.agno_tool_results` and the payload row in `fs.agno_fs`, both with `namespace=tool-results/postgres-layout-4e329620` and the same path, 47,249 bytes, version 1. The stored tool message was 821 characters for a 47,249-character result. After `delete_session`, 0 payload rows were left in `fs.agno_fs`. No warnings, no traceback.

---

### 07_delete_session_cascade.py

**Status:** PASS

**Description:** Two users (`alice`, `bob`) in two sessions; `delete_session` of alice's session first as bob, then as alice.

**Result:** Both runs answered 12 open P1 tickets (every 97th of 1,200). Before any delete each session had 1 index row and 1 payload. The delete as bob returned False and left alice's row and payload in place; the delete as alice returned True and removed both, while bob's stayed at 1 and 1. No warnings, no traceback.

---
