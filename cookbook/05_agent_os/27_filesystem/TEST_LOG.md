# Test Log

Not run yet. Repository instructions require waiting for explicit user approval
before running the cookbook or automated tests.

---

### read_only_consumer.py

**Status:** PASS

**Description:** Imported the app and drove it with a FastAPI test client (no server, no model call). A recorder holds `FileSystem(db, namespace="research/decisions")`; an answerer holds the same store as `FileSystem(db, namespace="research/decisions", read_only=True)`. Seeded `decisions/2026-09.md`. Re-checked 2026-09-28 after tool options moved onto `FileSystem`: the answerer resolves to read-only access and the recorder to full access.

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

### with_user_isolation.py (unit-level, no model)

**Status:** PASS

**Description:** Exercised the isolation semantics this cookbook relies on through the unit suites rather than a model run: under `user_isolation=True` the managed namespace stays `personal-assistant` and tool calls act in the verified user's partition; without it every user shares the store; an admin lists every partition and can open any user's file; another user, and a run with no user, cannot read the files; the browser routes resolve the same partition. The explicit table upgrade (`DbFileSystem.upgrade_schema()`) was verified on SQLite (unit test) and live Postgres (smoke), and an outdated table is refused until it runs.

**Result:** All partition and upgrade tests pass. Agent runs against a model were not exercised.

---

### os_level_filesystem.py

**Status:** PASS

**Description:** Run on 2026-11-24 with `.venv/bin/python cookbook/05_agent_os/27_filesystem/os_level_filesystem.py`, served on port 7777, and requested with curl. No model call. The AgentOS declares two file systems, `handbook` and `shared`. Four agents are served: the writer holds `shared`, the editor holds `drafts` and `shared` read-only, the notes agent uses `filesystem=True`, and the plain agent holds none.

**Result:** `/config` listed four entries, each with an `id`: `handbook` (`declared: true`, `agents: []`), `shared` (`declared: true`, agents `editor` read-only and `writer`), `drafts` and `notes-agent` (`declared: false`). `/filesystem/entries?filesystem_id=handbook` listed the `onboarding` directory with `agent_ids: []`, `/filesystem/content?filesystem_id=handbook&path=onboarding/welcome.md` returned the seeded page, `/filesystem/search?filesystem_id=shared&query=filesystem` found `notes/standup.md`, and `/filesystem/files` listed the three seeded files, each row with its `filesystem_id`. `namespace=handbook` and `agent_id=editor` still returned 200, and an id nothing uses returned 404. `/agents` reported no file system for the plain agent. Agent runs against a model were not exercised.

---

### os_level_filesystem.py (after the review fixes)

**Status:** PASS

**Description:** Requested on 2026-11-25 through a FastAPI test client on the cookbook's `app`, not on a served port. No model call. The same stores and agents as above.

**Result:** `/config` listed the same four entries. `agent_id=editor` opened `drafts`, and `agent_id=editor&filesystem_id=shared` opened `shared` with `agent_ids` `editor`, the agent the request names. `agent_id=editor&filesystem_id=handbook` returned 404: the editor does not hold the handbook. `/filesystem/files?agent_id=editor` listed the editor's two files under the ids `drafts` and `shared`, the ids the unfiltered listing gives them.

---

### multiple_stores_agent.py (store descriptions)

**Status:** PASS

**Description:** Imported the module on 2026-11-25 and resolved the analyst's tools (no server, no model call). `analyst/drafts` and `team/handbook` each carry a `description`.

**Result:** Every tool of a store starts its description with the namespace and the purpose, for example `fs_2_team_handbook_read_file`: `Filesystem namespace: 'team/handbook'. Purpose: The team handbook. Read the style guide here before writing.` Each store's instructions carry the same two lines first. The drafts store resolved seven tools and the handbook three. An agent run against a model was not exercised: `OPENAI_API_KEY` was not set, so whether the model picks the right store from the descriptions is not measured.

---
