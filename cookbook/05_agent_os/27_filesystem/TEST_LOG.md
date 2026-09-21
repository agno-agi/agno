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

### multiple_stores_per_agent.py (filesystem list API update)

**Status:** NOT RUN

**Description:** Updated the example to use a mixed `filesystem` list containing a
plain writable store and a read-only toolkit. Both stores expose independent read
tools, and the drafts store also exposes write tools.

**Result:** Awaiting explicit approval to run. Earlier PASS entries describe the
previous manual-toolkit implementation, not this revision.

---

### read_only_consumer.py (agent access config update)

**Status:** NOT RUN

**Description:** The config now lists agent objects with optional `access`, which
defaults to `"full"`. Read-only agents carry `access: "read_only"` on their entry.

**Result:** Source and regression expectations updated; tests and cookbook not run.
Earlier config output in this log records the previous schema.

---
