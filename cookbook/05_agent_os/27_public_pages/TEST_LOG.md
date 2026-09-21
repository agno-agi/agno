# Public pages test log

### public_control_plane.py (2026-09-08)

**Status:** PASS

**Description:** Ran `public_control_plane.py --check` with the demo environment,
this worktree on `PYTHONPATH`, and a locally generated RS256 verification public
key. No model or database call was needed for the configuration check.

**Result:** Public chat, the explicit MCP tool and JWT API access assembled
successfully. Composed HTTP/WebSocket coverage is in
`libs/agno/tests/integration/os/test_public_authorization.py`; a hosted Control
Plane connection remains a deployment check.

---

### full_page.py — complete page reads and fence-aware normalization (2026-09-08)

**Status:** PASS

**Description:** Ran `full_page.py --help` and `--normalize` using the demo Python
with this checkout on `PYTHONPATH`. The normalization input contains a four-backtick
Markdown example with literal triple backticks, component markup and HTML entities.

**Result:** CLI help passed without database/provider setup. Prose entities were
decoded while the nested code example remained unchanged. Full-page API behavior
is covered separately by sync/async unit and PostgreSQL integration tests.
The cookbook's live corpus/provider modes were not run.

---

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

### page_filesystem.py

**Status:** PASS

**Description:** Published a deterministic corpus in a disposable PostgreSQL database,
then ran the documented script in three fresh `.venvs/demo/bin/python` processes
with `PAGE_DEMO_DB_URL` selecting that database. Invocations were `cat /agent`,
`rg Standalone /agent`, and `ls /`. Each process imports its own Knowledge instance
and calls setup; no preinitialized instance is injected into the example.

**Result:** PASS for all three standalone commands. The previous script fails
in the same environment with the missing `Knowledge.setup()` error. No live
provider, production database, deployment or release was used.

### page_filesystem.py explicit tools

**Status:** PASS

**Description:** Reran standalone cat, rg and ls in fresh demo-environment
processes after replacing the handwritten wrapper with `page_files.tools()` and
adding optional `--ask` Agent execution. The default CLI constructs the Agent
and toolkit but reads directly, without a provider call.

**Result:** All three commands returned the expected published content. Separate
deterministic Agent-loop tests cover sync/async tool selection, schemas, custom
descriptions and page-error results. The live-provider `--ask` mode was not run.

---

### public_pages.py — public MCP lifecycle configuration (2026-09-08)

**Status:** PASS

**Description:** Ran `public_pages.py --help` after removing the unnecessary
`lifecycle_tools=False` override. Module import builds the public AgentOS app,
so this checks that the default lifecycle setting permits its custom MCP tools.

**Result:** App construction and CLI help passed. The initial shared demo
environment failed to import `MCPError` because it has an older MCP dependency.
The successful run used the demo Python with the development environment's
compatible packages and temporary `pgvector` dependencies on `PYTHONPATH`;
neither shared environment was modified. Live database/provider modes were not
run. The focused public-configuration and MCP suites passed all 204 tests.

---


## 2026-09-09 documentation Markdown transform

- PASS: `documentation_markdown.py` ran with the demo Python and candidate source. Produces labeled Markdown and one chunk without network/model calls.
- PASS: 30 normalization and chunking tests, including the existing application fixtures, nested/mismatched fences, serializer escapes, Unicode and callback isolation.
- PASS: two disposable PostgreSQL publication tests cover sync and async transforms and repeat-sync embedding reuse.
- PASS: full format and validation scripts.
- Compatibility comparison: all 3,909 local published pages yield identical old/new transformed bytes and chunks, and are unchanged on repeat normalization. This is a published-text corpus comparison, not a full raw-source crawl.
- Raw-source sample: 24 of 40 public Markdown pages fetched successfully (18 contained sampled component types); all 24 match old/new bytes and chunks. The other 16 URLs returned HTTP 500 and were excluded from equivalence claims.
- No index mutation, re-embedding, reader default change or production deployment. Generic repeated entity decoding is not guaranteed idempotent; the documented transform operates on source once.

## 2026-09-09 native MCP routing

- 282 composed MCP server/OAuth/routing/public-JWT cases passed.
- 24 routing cases passed after adding included-router-prefix conflict checks;
  these overlap the composed suite. Covers root, native/legacy/custom paths,
  actual ASGI submounts, initialize/catalog/quota parity, browser versus SSE GET,
  JWT REST protection, canonical cards, Host ambiguity/case/ports/forwarding,
  and startup rejection of unsupported custom OAuth routing.
- The complete existing native OAuth flow remains supported at /mcp. Custom
  OAuth routes are deliberately rejected rather than publishing a wrong resource.
- Cookbook mcp_domain.py --check passed. Full format and validation passed.
- No DNS, hosting or production application changes were made.

---

### migrate_page_source.py (2026-09-17)

**Status:** PASS

**Description:** Drove the CLI as a subprocess against a disposable local
PostgreSQL 18 database created by the page storage test fixture, with the demo
module's own `Knowledge`, a stub embedder in place of OpenAI, in-memory page
fetching and a placeholder API key: `--help` with the database URL pointed at a
closed port; the default dry run on uninitialized storage; seeding at the old
host; dry run; `--apply`; a repeated `--apply`; a dry run once the target is
current; an invalid `http://` target; and `public_pages.py sync` still configured
with the old source. The same sequence is maintained as
`test_source_relocation_cli_reports_each_outcome_and_keeps_setup_visible` in
`libs/agno/tests/integration/knowledge/test_page_storage.py`.

**Result:** `--help` exits before the demo import. The dry run on fresh storage
runs `setup()`, creates the page schema and binding row, then rejects the unbound
namespace. After seeding, the dry run leaves the binding unchanged and says so;
`--apply` moves the source and increments the revision once; the repeated apply
and the dry run at target report that the binding already points to the target
with no further increment; the invalid target fails with `invalid_source_url` and
prints no success text; the stale producer is refused with "bound to another
documentation source" and the binding is not rewritten. No provider was called.
Chat, serve and MCP modes were not run.

---

### Source relocation operator API (2026-09-17)

**Status:** PASS

**Description:** Focused runs on the PR head with the local review changes
(uncommitted) against a disposable local PostgreSQL 18 database created per
module by the fixture: `libs/agno/tests/unit/knowledge/test_page_contract.py`
(19 passed, exact public-export set with `PageSourceBinding`,
`PageSourceMigration` and `PageSourceBusy` checked in a storage-blocking
subprocess) and `libs/agno/tests/integration/knowledge/test_page_storage.py`
(153 passed, 0 skipped, including the relocation cases). Environment: Python
3.12.13, pytest 9.1.1, SQLAlchemy 2.0.52, psycopg 3.3.5 (binary), pgvector 0.5.0.

**Result:** Sync and async inspect and migrate, dry run, apply and idempotent
retry; held-lock contention with `PageSourceBusy` for sync and async competitors
and an independent namespace proceeding; sync waiting behind a held relocation
and refusing the old source afterward; readers during an uncommitted update;
cancellation before commit (rolled back) and during commit (committed); a
simulated lost commit acknowledgement with guarded retry; worker-pool and
connection-pool exhaustion; the URL validation matrix; binding-only persistence
checked with plain SQL against catalog, filesystem, vector and binding tables;
citation refresh through list, read, grep, search and legacy search without
document embeddings, with changed-content and `public_url` controls; and
list-cursor restart after apply. `ruff check`, `ruff format --check` and the
cookbook pattern check passed. `mypy` reports 53 pre-existing errors in 13
unrelated modules, identical on the PR base and head; no new diagnostics.

---

## 2026-09-09 typed page-tool outcomes

- PASS: 267 composed command/filesystem/lazy-read/tool/MCP cases, including 66 archived command outputs unchanged, literal-grep completeness, typed grammar/missing-path/storage errors, no false error from page prose, Unicode JSON bounds, MCP schemas/isError, search parity and run reference tracking.
- PASS: `page_tool_results.py` with demo Python. The default `check` mode validates configuration without storage/provider calls; `sync` published 174 of 175 discovered pages against the shared `ai` database; `run "ls /"` returned a typed successful result and `cat /no-such-page` returned `is_error=True` with `page_not_found`.
- PASS: full format and validation scripts.
- FIXED: an empty page index returned before command validation, so invalid syntax, unsupported commands, pipes and missing paths all reported `is_error=False` and MCP saw success. The empty-index message now follows validation; malformed input stays an error and a valid command against an empty index still reports it.
- Existing chat command tools retain their character-bound text contract. Direct typed/MCP command results additionally bound the complete result JSON; MCP envelope overhead remains under the transport's own limits. No product feedback or score-interpretation policy moved upstream.

---

### public_pages.py sync-docs and page_sync_progress.py (2026-09-21)

**Status:** PASS offline and live. The live sync reported `partial` twice before
`unchanged`; see the live results.

**Description:** Page sync progress from Knowledge, through the `sync-docs` workflow
function step, over the AgentOS REST/SSE workflow route, to `AgentOSClient`.
Python 3.12.13, pytest 9.1.1, httpx-based `AgentOSClient`, PostgreSQL 18.1 with
pgvector 0.8.1. All commands ran with `PYTHONPATH=libs/agno`.

**Result:**
- `pytest libs/agno/tests/unit/os/test_client.py libs/agno/tests/unit/knowledge/test_page_contract.py
  libs/agno/tests/unit/workflow/test_function_progress.py
  libs/agno/tests/unit/workflow/test_workflow_event_stream.py
  libs/agno/tests/unit/knowledge/test_sync_progress_workers.py
  libs/agno/tests/unit/test_py39_compat.py`: 107 passed, 2 skipped, twice with
  identical results. The skips are sync execution with an async executor, which
  sync execution rejects by design.
- `AgentOSClient.run_workflow_stream()` parses a `StepProgress` SSE event into
  `StepProgressEvent` with its content, data, run, session, step and attempt, and
  forwards the `Authorization` header. Without the event's registry entry the
  client drops it and these tests fail.
- `pytest libs/agno/tests/integration/os/test_workflow_runs.py`: 19 passed, twice. A
  function step's progress reaches the real client through the real route before
  `StepCompleted` and `WorkflowCompleted`; the final content stays the report; a
  second run carries nothing over from the first.
- The cookbook step yields `Waiting to synchronize pages`, `Discovered 2 pages`,
  `Processed 2 of 2 pages (1 updated, 1 failed)`, `Pruned 3 stale pages`, the full
  snapshot in `data`, then the `SyncReport`; a `partial` report marks the step
  unsuccessful, and a request the schema rejects never reaches the page source.
- The `sync-docs` workflow streams every `StepProgress` and saves none of them with
  the run: AgentOS stores run events, and the workflow skips this one because there
  is one per page. The saved run keeps `StepCompleted`, `WorkflowCompleted` and the
  report, on a first and a second run.
- `page_sync_progress.py` prints progress in order and then the report, exit 0. It
  exits non-zero on a workflow error, a cancellation, no progress, no report and a
  `partial` report, and exits 2 without calling the server when
  `PAGE_DEMO_SYNC_TOKEN` is unset. The token never appears in its output. It sends
  only `message` and `stream`; the request holds `reason` and `reindex`.
- Security, `AGNO_PAGE_TEST_DB_URL=... pytest libs/agno/tests/integration/os/test_public_surface.py`:
  7 passed, twice. An anonymous streaming request to `sync-docs` returns 401; the
  trusted token receives `StepProgress` before `WorkflowCompleted` and the report
  as final content.
- `pytest libs/agno/tests/unit/workflow`: 795 passed, 9 skipped.
  `pytest libs/agno/tests/unit/knowledge`: 1105 passed, 13 skipped.
- `AGNO_PAGE_TEST_DB_URL=... pytest libs/agno/tests/integration/knowledge/test_page_storage.py`:
  159 passed, none skipped, including sync/async progress counts, terminal partial
  status and observer failure isolation on both `sync_pages` and `async_sync_pages`.
  The progress tests ran twice in separate temporary databases; none were left behind.
- On Python 3.9.6 with the storage coordinator stubbed, `astream_sync_pages`
  iterates to the terminal result; `contextlib.aclosing` does not exist there.
- `ruff check` and `ruff format --check` passed for every changed file. `validate.sh`
  reports the same 53 `mypy` errors as main, no new diagnostics. The cookbook
  pattern check reports `missing_sections` for `page_sync_progress.py`, as it does
  for the other nine files in this folder on main.

**Live results (2026-09-21):** `public_pages.py serve` on `127.0.0.1:7777` with a new
`page_demo` database, `text-embedding-3-small` embeddings and `gpt-5.6-luna`
responses. Source `https://llmstxt.org/llms.txt`: HTTP 200, three links, all on
`llmstxt.org` (`index.md`, `intro.html.md`, `ed.md`).
- Startup was clean. The only listening socket was `127.0.0.1:7777`. `/health` 200;
  `/readyz` `{"status":"ok","database":"ok","request_limits":"ok"}`; `/agents` listed
  only `docs`; `/config`, `/docs` and `/workflows` returned 404, as this public
  surface intends.
- Anonymous and wrong-token requests to `/workflows/sync-docs/runs` returned 401.
- `page_sync_progress.py`, run three times with the trusted token. Progress lines
  preceded the report every time, and neither the token nor the key was printed.
  1. `Waiting to synchronize pages` twice, `Discovered 3 pages`, `Processed 1 of 3
     pages (1 updated, 0 failed)`, `Processed 2 of 3 pages (2 updated, 0 failed)`,
     `Processed 3 of 3 pages (2 updated, 1 failed)`. Report `partial`: updated 2,
     failed 1, `page_sync_failed`. The server logged `Step reconcile failed (attempt 1):
     sync_failed`, so the step retried and each attempt reported `Waiting`.
  2. `Processed 1 of 3 pages (0 updated, 0 failed)`, `Processed 2 of 3 pages (0
     updated, 1 failed)`, `Processed 3 of 3 pages (1 updated, 1 failed)`. Report
     `partial`: updated 1, failed 1. The page that failed in run 1 published; an
     already published, unchanged page failed its refresh and kept its revision.
  3. Three lines with `0 updated, 0 failed`, then `Pruned 0 stale pages`. Report
     `unchanged`, no failures. Unchanged pages were not embedded again.
- Each failure was `Page sync failed (SyncFailed)` on a different page. All three
  pages returned 200 to `curl` in under a second. Forty direct calls to the existing
  page fetcher against this source all succeeded but took 0.5 to 19 seconds per
  page, against its 30 second limit. The failures were not reproduced outside a
  sync.
- `page_filesystem.py "ls /"` listed `ed.md`, `index.md` and `intro.html.md`.
- The server's `search_docs` tool, queried for `purpose of llms.txt proposal`,
  returned nine results across the three pages, the `Proposal` section first with
  score 0.80, every URL on `llmstxt.org`, `partial` false.
- The `docs` agent streamed an answer to "What does the llms.txt proposal
  recommend, and which documents are linked from its index? Cite the source URLs."
  with two tool calls and citations to `https://llmstxt.org/`. All 30 links it
  listed are present in the source page.
- `page_demo` stored three workflow sessions and one agent session. No temporary
  database was created and every table the demo made is inside `page_demo`.
- The server stopped on interrupt and port 7777 closed. `page_demo` was kept.
  `git status` was identical before and after the live run.
- NOT RUN: `--reindex`. MCP delivery and Control Plane or AG-UI rendering are not
  part of this example and were not exercised.

---
