# Context Cookbook Test Log

All end-to-end runs used the demo venv (`.venvs/demo/bin/python`)
against real OpenAI (`gpt-5.4` / `gpt-5.4-mini`).

## 2026-04-22

### 00_filesystem.py

**Status:** PASS

**Description:** `FilesystemContextProvider` rooted at the cookbook
directory; agent lists and reads files.

**Result:** Agent called `query_cookbooks` once, listed every Python
file in the directory, opened `07_custom_provider.py`, and quoted
the docstring verbatim.

---

### 01_web_exa.py

**Status:** Smoke-only (no EXA_API_KEY available locally)

**Description:** `WebContextProvider(backend=ExaBackend())`.

**Result:** Without a key, `web.status()` returns
`Status(ok=False, detail='EXA_API_KEY not set')` — clean, no crash.
`get_tools()` returns `[query_web]` as expected. End-to-end web
research to be verified once an Exa key is available.

---

### 02_database_read_write.py

**Status:** PASS

**Description:** `DatabaseContextProvider` against a freshly-seeded
SQLite file. Writes "Grace Hopper" via `update_contacts`, then reads
every contact back via `query_contacts`, then verifies at the SQL
level.

**Result:** Write tool inserted the new contact; read tool returned
both rows (Ada Lovelace, Grace Hopper); direct SQL check passed.

---

### 03_slack.py

**Status:** PASS

**Description:** `SlackContextProvider` against a real Slack
workspace.

**Result:** Provider authenticated with the bot token, sub-agent
called `list_channels`, returned the workspace's public channels.
Prompt is scoped so it only needs `channels:read` + `users:read`;
the other tools (`search_workspace`, `get_channel_history`,
`get_thread`) are still exposed to the sub-agent for broader
queries when the bot has the needed scopes / channel memberships.

---

### 04_mcp_server.py

**Status:** PASS

**Description:** `MCPContextProvider` against `uvx mcp-server-time`
(stdio MCP server). Exercises explicit `asetup` / `aclose`
bracketing and `mode=ContextMode.tools` (flat tools on the caller).

**Result:** `asetup()` connected in under a second; `astatus()`
reported `mcp: time (2 tools)`; agent called
`get_current_time(Asia/Tokyo)` and answered correctly; `aclose()`
closed the session without error.

---

### 05_google_drive.py

**Status:** PASS

**Description:** `GDriveContextProvider` against a real service
account key. Exercises `AllDrivesGoogleDriveTools` for
shared-folder / Shared-Drive coverage.

**Result:** Provider loaded the SA JSON, authenticated to the Drive
API, and the sub-agent issued a Drive search via `search_files`.
The SA had no documents shared with it in the workspace used for
testing, so the agent correctly reported "none visible" — but every
layer of the stack (auth → tool invocation → `corpora=allDrives` →
agent synthesis) ran end-to-end.

---

### 06_multi_provider.py

**Status:** PASS

**Description:** fs + web + db composed on one agent.

**Result:** Agent fanned out `query_cookbooks` and `query_releases`
in one turn and answered both sub-questions.

Caught + fixed a real bug during testing: the cookbook originally
used `sqlite:///:memory:`, which creates a per-connection DB — the
SQL sub-agent opened its own connection and saw an empty database.
Switched to a temp-file SQLite DB; round-trip now works.

---

### 07_custom_provider.py

**Status:** PASS

**Description:** Subclass `ContextProvider` in-place (in-memory FAQ
dict).

**Result:** Agent called `query_faq`, got the return-policy entry
back, and answered the user's question.

---
