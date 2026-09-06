# Public pages test log

### public_pages.py — callable dependency context (2026-09-06)

**Status:** PASS

**Description:** Replaced the context pre-hook with an explicit async `docs_context` dependency. The application still chooses the query, calls `search_docs` and places evidence at the same instructions placeholder. `add_dependencies_to_context` remains unset at its existing `False` default. Product Docs Agent code retains its pre-hook.

**Result:** Ran `--help` and an offline executable probe in `.venvs/demo` with `PYTHONPATH=libs/agno`. Streaming/non-streaming chat, whitespace trimming, blank/non-text/absent inputs, fresh multi-turn context and three follow-up suggestions passed with recording models and a recording search function. Planner defaults and HNSW breadth remain unchanged. Framework public-run regressions compare both sync/async and streaming/non-streaming prompt/history/follow-up inputs, model retry reuse, continuation input/session injection and concurrent input isolation. Required format/validation scripts passed.

**Limits:** This validation makes no live retrieval/provider, HTTP or MCP claim. Earlier live results below retain their original executable hashes. Dependency resolution runs before pre-hooks, reuses successful values on model retries and emits no pre-hook events; it is not a claim of identical hook lifecycle or improved live latency.

**Executable SHA-256:** `e9122dd16a779f29529a29713b7b6509b41551e82dc3735eebbbc46812d63d86`

---

### public_pages.py — default planner configuration (2026-09-06)

**Status:** PASS

**Description:** Removed the optional planner overrides while retaining explicit `HNSW(ef_search=200)`. Ran the executable with `--help` in `.venvs/demo`, then loaded it with `runpy` and checked that `knowledge.page_search` is unset, its resolved planner configuration uses the framework defaults, HNSW breadth remains 200, and the database is shared as configured.

**Result:** Demo CLI/configuration checks, required `scripts/format.sh` and `scripts/validate.sh`, and all four existing PostgreSQL planner-default/override/restoration cases passed. The PostgreSQL tests used a disposable database. No live model calls, source sync, HTTP serving or MCP run was repeated for this cookbook-only configuration change; earlier live results below apply to their recorded executable versions.

**Commands:** `PYTHONPATH=libs/agno .venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py --help`; `.venv/bin/python -m pytest -q libs/agno/tests/integration/knowledge/test_page_storage.py::test_search_tuning_honors_hnsw_and_operator_defaults_without_leaking` with the isolated local database URL configured.

**Executable SHA-256:** `cc03e7dff96a8334d11b6a73fcccf663c29b57dfa2f934046501a48fee571c6d`

---

### public_pages.py — explicit search configuration and lifecycle fixes

**Status:** PASS

**Description:** Re-ran the updated executable in the owned `.venvs/demo` environment against a disposable PostgreSQL database. Discovery was bounded to the real public Agents overview page; fetch, embeddings, chat and follow-up models, HTTP/SSE, native MCP, authenticated durable sync and polling used their real implementations.

**Result:** Sync/read/grep, explicit pre-hook chat, follow-up completion, readiness, selected roster, CORS, MCP discovery/search, anonymous workflow rejection and authorized background refresh all passed. The database was dropped. The example explicitly supplies `HNSW(ef_search=200)` and `PageSearchConfig`, using preferred `content_db`. This single-page smoke test establishes executable integration, not full-corpus quality or live latency acceptance.

**Executable SHA-256:** `93b78e7699e71b785eda0db40d7032c83ce6b2c52dc46c21b14c46f1503ebf7b`

---

### public_pages.py

**Status:** PASS

**Description:** Fresh validation on 2026-09-05 after narrowing the migration. Used the owned `.venvs/demo` environment, PostgreSQL 18.1/pgvector, real `text-embedding-3-small` embeddings and `gpt-5.6-luna` responses. Discovery was explicitly limited to one real public page, `https://docs.agno.com/agents/overview.md`; fetch, publication, query embeddings, streamed model responses, HTTP and MCP followed the real implementations.

**Result:** Setup/sync/read/grep, explicit pre-hook chat, HTTP SSE with follow-up completion, selected Agent listing, readiness/CORS, explicit MCP card URL, actual MCPTools search, anonymous sync rejection, and authenticated durable background sync/status polling passed. Background refresh returned unchanged. The isolated database was dropped. No full-site sync or deployment was performed.

**Validation scope:** That executable used explicit instructions/pre-hook/tools and existing URL configuration. Product recording-model tests independently check prompt, multi-turn/tool-loop evidence and follow-up suggestions. Earlier automatic-reference/Team/derived-URL example results are preserved separately and do not validate this example.

---

### public_team.py

**Status:** PASS

**Description:** Ran `public_team.py --check` with the demo environment and candidate Agno. Selected Team binding and app construction succeeded without provider calls.

**Result:** Configuration validated. Server/provider execution was not run; deterministic native HTTP Team tests cover the protocol separately.

---

### public_pages.py

**Status:** PASS

**Description:** Ran `public_pages.py --help` in an isolated demo environment using the candidate framework and declared MCP 2.x/FastMCP 4.x dependencies. The initially inherited demo environment had incompatible MCP 1.x; it was left unchanged.

**Result:** Constructor wiring and CLI import passed. Live sync/chat/MCP-client modes were not run. Disposable PostgreSQL publication and paired product composition tests cover deterministic operation separately.

---
