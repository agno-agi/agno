# Test Log

Not run yet. Repository instructions require waiting for explicit user approval
before running the cookbook or automated tests.

---

### read_only_consumer.py

**Status:** PASS

**Description:** Imported the app and drove it with a FastAPI test client (no server, no model call). A recorder holds `FileSystem(db, namespace="research/decisions")`; an answerer holds the same store through `filesystem=decisions.tools(read_only=True, add_instructions=True)`. Seeded `decisions/2026-09.md`.

**Result:** `/config` reported one instance with `agents=["answerer", "recorder"]` and `read_only_agents=["answerer"]`. `/filesystem/entries?agent_id=answerer` and `/filesystem/files` listed the seeded file. The answerer resolved to `list_files`, `read_file`, `search_content` only; the recorder to the default seven tools. Agent runs against a model were not exercised.

---

### multiple_stores_per_agent.py

**Status:** PASS

**Description:** Imported the app and drove it with a FastAPI test client (no server, no model call). One agent attaches `analyst/drafts` (write tools via `include_tools`) and `team/handbook` (`read_only=True`) through `tools`. Seeded one file in each.

**Result:** `analyst.filesystems` returned both stores with the right read-only flags. `/filesystem/entries?agent_id=analyst` browsed the drafts, `?namespace=team/handbook` browsed the handbook and read `style.md`, and `/filesystem/files` listed both namespaces. The agent resolved six tools with no name collision. Agent runs against a model were not exercised.

---

### multiple_stores_per_agent.py (live server, browser request shapes)

**Status:** PASS

**Description:** Served the app with uvicorn on a spare port and requested the exact URLs and query parameters the Agno OS File System page builds: the global table with and without `query`, the agent view (`agent_id` with an empty `directory`), a subdirectory, opening a global row (`agent_id` + `namespace` + `path`), and agent search.

**Result:** All returned 200 with the expected entries, and responses carried the resolved `namespace` and `agent_ids`. The former `/files` and `/agents/{agent_id}/files` paths return 404. OpenAPI lists `list_filesystem_files`, `list_filesystem_entries`, `read_filesystem_content` and `search_filesystem`.

---
