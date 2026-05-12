# Context Cookbook Test Log

All end-to-end runs used the demo venv (`.venvs/demo/bin/python`)
against real OpenAI (`gpt-5.4` / `gpt-5.4-mini`).

## 2026-04-28

### 16_wiki_with_web.py

**Status:** PASS

**Description:** `WikiContextProvider(backend=FileSystemBackend(...), web=ExaMCPBackend())`.
Asks the agent to ingest CPython's release schedule (PEP 602 / python.org)
into `papers/cpython-release-cycle.md` via `update_wiki`, then read it
back via `query_wiki`.

**Result:** Write sub-agent called the Exa MCP `web_search` + `web_fetch`
tools, digested the source into a markdown page (2349 bytes), and filed it
under `papers/`. Read sub-agent answered the follow-up citing the page.
Direct filesystem assertion confirmed at least one page under `papers/`.

---

### 17_wiki_dual.py

**Status:** PASS

**Description:** Two `WikiContextProvider` instances composed on one agent:
`company_knowledge` (full read+write, FileSystemBackend) and `company_voice`
(read-only via `write=False`, FileSystemBackend pre-seeded with X +
LinkedIn voice rules).

**Result:** Outer agent surface contained exactly three tools:
`query_company_knowledge`, `update_company_knowledge`, `query_company_voice`
— no `update_company_voice`. Agent called `query_company_voice` first,
then drafted a LinkedIn post that followed the seeded voice rules
(hook → proof → takeaway, plain prose, concrete example). Final
assertion confirmed the absent update tool.

---

### 14_wiki_filesystem.py

**Status:** PASS

**Description:** `WikiContextProvider(backend=FileSystemBackend(...))` rooted
at a fresh `demo-wiki/` directory. Asks the agent to add
`docs/deploys.md` via `update_wiki`, then reads it back via
`query_wiki`.

**Result:** Write sub-agent created `docs/deploys.md` with the
requested Prerequisites / Steps / Rollback sections; read sub-agent
listed the wiki, opened the new file, and answered the question
citing the file path. Direct filesystem assertion confirmed the
file landed on disk (493 bytes).

---

### 15_wiki_git.py

**Status:** Skipped (no `WIKI_REPO_URL` / `WIKI_GITHUB_TOKEN` available locally)

**Description:** `WikiContextProvider(backend=GitBackend(...))` against
a real GitHub repo. After the write sub-agent returns, the backend
stages, commits with an LLM-summarised one-line message, rebases
onto the remote, and pushes. PAT auth.

**Result:** Without the env vars set, the cookbook prints the opt-in
hint and exits cleanly — no side effects. Token scrubbing and
re-clone safety are covered by the unit tests.

---

## 2026-04-27

### 12_engineering_briefing.py

**Status:** Smoke-only (live Slack + Parallel credentials not
exercised locally)

**Description:** Three-provider engineering briefing demo. Slack
topics are matched against the local Agno workspace and enriched with
Parallel web search.

**Result:** `py_compile` passed; targeted Ruff passed. Import smoke
with dummy `OPENAI_API_KEY`, `PARALLEL_API_KEY`, and
`SLACK_BOT_TOKEN` confirmed the outer agent exposes `query_slack`,
`update_slack`, `query_agno`, and `query_web`; Slack exposes
bot-token-compatible reads in CLI while adding `search_workspace` only
when Slack interface metadata provides an action token.

---

## 2026-04-22

### 00_filesystem.py

**Status:** PASS

**Description:** `FilesystemContextProvider` rooted at the cookbook
directory; agent walks the directory to explain agno.context setup.

**Result:** Agent called `query_cookbooks`, read the README and the
custom-provider example, laid out the minimal setup steps, and cited
the files it pulled from.

---

### 01_web_exa.py

**Status:** Smoke-only (no EXA_API_KEY available locally)

**Description:** `WebContextProvider(backend=ExaBackend())`.

**Result:** Without a key, `web.status()` returns
`Status(ok=False, detail='EXA_API_KEY not set')` — clean, no crash.
`get_tools()` returns `[query_web]` as expected.

---

### 02_web_exa_mcp.py

**Status:** PASS

**Description:** `WebContextProvider(backend=ExaMCPBackend())` —
keyless endpoint at `https://mcp.exa.ai/mcp`. Exercises the
backend's `asetup` / `aclose` lifecycle forwarded through the
provider.

**Result:** Provider connected, status reported `mcp.exa.ai
(keyless)`, agent answered a CPython-release question and cited
python.org URLs; session closed cleanly.

---

### 03_web_parallel.py

**Status:** Smoke-only (no PARALLEL_API_KEY available locally)

**Description:** `WebContextProvider(backend=ParallelBackend())`.

**Result:** Without a key, `web.status()` returns
`Status(ok=False, detail='PARALLEL_API_KEY not set')` — clean.
`get_tools()` returns `[query_web]`.

---

### 04_database_read_write.py

**Status:** PASS

**Description:** `DatabaseContextProvider` against a freshly-seeded
SQLite file. Writes "Grace Hopper" via `update_contacts`, then reads
every contact back via `query_contacts`, then verifies at the SQL
level.

**Result:** Write tool inserted the new contact; read tool returned
both rows; direct SQL check passed.

---

### 05_slack.py

**Status:** PASS (read path); write path not E2E tested to avoid
posting to a real workspace — unit test covers routing.

**Description:** `SlackContextProvider` against a real Slack
workspace. Default surface is `query_slack` + `update_slack`, with
separate read and write sub-agents. Cookbook runs the read prompt
always; opts into posting only when `SLACK_WRITE_CHANNEL` is set.

**Result:** Read sub-agent authenticated with the bot token, called
`list_channels`, returned the workspace's public channels with
purposes. Without `SLACK_WRITE_CHANNEL` set the cookbook prints the
opt-in hint and exits — no side effects.

---

### 06_mcp_server.py

**Status:** PASS

**Description:** `MCPContextProvider` against `uvx mcp-server-time`
(stdio). Exercises `asetup` / `aclose` bracketing and
`mode=ContextMode.tools` (flat tools on the caller).

**Result:** `asetup()` connected; `astatus()` reported
`mcp: time (2 tools)`; agent called `get_current_time(Asia/Tokyo)`
correctly; `aclose()` closed cleanly.

---

### 07_google_drive.py

**Status:** PASS

**Description:** `GDriveContextProvider` against a real service
account. Exercises `AllDrivesGoogleDriveTools` for shared-folder /
Shared-Drive coverage.

**Result:** Auth + search ran end-to-end. The SA had no docs in the
test workspace; agent reported "none visible" correctly.

---

### 08_multi_provider.py

**Status:** PASS

**Description:** fs + web (Exa MCP, keyless) + db composed on one
agent. Only the web provider needs `asetup` / `aclose`; the
cookbook brackets just that one, showing the selective-lifecycle
pattern.

**Result:** Agent fanned out `query_cookbooks` and `query_releases`
in one turn and answered both sub-questions.

Earlier run (before the switch) caught + fixed a real bug: the
cookbook originally used `sqlite:///:memory:`, which creates a
per-connection DB — the SQL sub-agent opened its own connection
and saw an empty database. Switched to a temp-file SQLite DB.

---

### 10_custom_provider.py

**Status:** PASS

**Description:** Subclass `ContextProvider` in-place (in-memory FAQ
dict).

**Result:** Agent called `query_faq`, got the return-policy entry,
and answered the user's question.

---

### 12_workspace.py

**Status:** Smoke-only (no OPENAI_API_KEY available locally)

**Description:** `WorkspaceContextProvider` rooted at the repository.
It wraps the read-only `Workspace` toolkit so project searches skip
virtualenvs, dependency folders, build outputs, caches, and agent
scratch directories by default.

**Result:** Imported the cookbook with
`PYTHONPATH=libs/agno .venvs/demo/bin/python` to verify construction.
Unit tests cover the provider surface and exclude behavior for
`.context` and `.venvs`.

---
