# Company chat Product creation hardening — October 19, 2026

Branch: `fix/company-chat-products-hardening`, based on `codex/company-chat-products`.

### 05_product_manager.py

**Status:** PASS

**Description:** Re-ran the chat step after the hardening changes: Routine
creation deletes its schedule when linking or enabling fails, Product creation
discards a partially created Product, the Product is checked before its
executor, both chat tools require `routines:write` with `schedules:write`, and
toolkits published only over MCP receive the OS registry. The example runs
unchanged and still creates the Product, website Source and intake Routine
under Alice's identity.

**Result:** Passed with `.venv/bin/python` on SQLite. No model call was made.
The chat suite with its five new cases and the Product Manager unit suite:
159 passed, 46 conditional skips (sync tools on async adapters). Every new case
fails on the `codex/company-chat-products` head and passes here. The Company
integration selection below: 1,534 passed, 48 conditional skips; the 44 cases in `test_company_sandbox_admission.py` fail on a `pymongo` import in this environment; the four MongoDB-dependent modules
were left out because `pymongo` is not installed in this environment. Company,
scheduler and heartbeat unit suites: 563 passed, one Telegram transport case
needs `telebot`, which is not installed here.

Reproduce the integration selection with:

```bash
PYTHONPATH=libs/agno \
AGNO_TEST_POSTGRES_URL=postgresql+psycopg://ai:ai@localhost:5532/ai \
.venv/bin/python -m pytest \
  libs/agno/tests/integration/db/test_company_*.py \
  libs/agno/tests/integration/db/test_{products,projects,tasks,schedule}_lifecycle_parity.py \
  libs/agno/tests/integration/db/sqlite/test_{products,projects,tasks}.py \
  -q --disable-warnings --tb=short -o log_cli=false
```

`ruff format` and `ruff check` pass. The shared development environment reports
mypy errors only in untouched database adapter and model provider files.

---

# Company chat Product creation — October 19, 2026

Branch: `codex/company-chat-products`, based on main `287bc588c3`.

### 05_product_manager.py

**Status:** PASS

**Description:** Added the chat step "Set up a Product for our docs site with an
intake Routine." The example invokes the same Company tool as Product Manager,
creates the Product, website Source and on-demand intake Routine under Alice's
identity, and checks that the records appear in the Product, Source and Routine
lists. The existing proposal, status and decision steps still pass.

**Result:** Passed with `.venv/bin/python` on SQLite. No model or external Source
fetch was made. The new integration suite also exercises Product Manager with a
deterministic model and a real Routine trigger on SQLite and PostgreSQL, sync
and async: 116 passed, 36 conditional skips (sync tools on async adapters).
All 14 core acceptance cases fail on clean main because the tools are absent.

The complete Company integration and Product/Project/Task/schedule lifecycle
selection passed 1,944 cases with 52 conditional skips. Eight replica subprocess
cases initially failed to import their worker module; all eight passed after
rerunning with `PYTHONPATH=libs/agno`. The final focused suite adds 12 passing
provider/dispatch cases beyond that selection: 1,964 distinct integration passes
and 56 conditional skips in total. MongoDB-only checks were not enabled.
The affected Company-tool, Product Manager, heartbeat, execution and scheduler
unit suites passed all 372 cases.

Reproduce the full integration selection with:

```bash
PYTHONPATH=libs/agno \
AGNO_TEST_POSTGRES_URL=postgresql+psycopg://ai:ai@localhost:5532/ai \
.venv/bin/python -m pytest \
  libs/agno/tests/integration/db/test_company_*.py \
  libs/agno/tests/integration/db/test_{products,projects,tasks,schedule}_lifecycle_parity.py \
  libs/agno/tests/integration/db/sqlite/test_{products,projects,tasks}.py \
  -n 4 -q --disable-warnings --tb=short -o log_cli=false
```

Formatting and full validation passed in the isolated Python 3.10 environment.
The shared development Python 3.12 environment reports nine typing errors in
three untouched provider files; the same nine errors reproduce on clean main.

---

# Company validation record — Task ownership and recovery

**Date:** October 16, 2026

**Branch:** `codex/company-task-recovery`

**Base:** `2dec52a7e7bf202c3913b1d442220227525ce73a`

**Validated tree:** the implementation, tests, README and examples in the commit
containing this record. The implementation was published for parallel review as
`51b03980c696c296a1780b31dad20001c2c1b561`; the final follow-up changes this validation
record only. The PR reports the final full commit SHA. This single record
supersedes the historical entries; Git retains their previous versions.

## Integration validation

**Status:** PASS — 1,744 distinct integration cases, including all 50 new
regressions. No skips or failures.

The four follow-up fixes preserve remote Running attempts, restore disabled-owner
checks for new work, implement MongoDB schedule-history retention, and provide a
native synchronous attention reader. `test_company_replica_offboarding.py` adds
50 regression cases:

- Eight real two-process checkpoint cases across four SQL adapters and both
  isolation modes. The worker has executed a tool and persists Running; another
  process loses the ticket and recovers twice without cancellation or replay.
  The worker then completes and the Task receives its completed result.
- Twenty-four disabled-owner cases across Agent, Team and Workflow, four SQL
  adapters and both isolation modes. A lost completed result still recovers;
  new manual and automatic work is refused; the automatic refusal records one
  failure and returns the Task to Backlog; an authorized collaborator can cancel
  existing work after its owner is disabled.
- Eight fail-closed directory checks across four SQL adapters and both isolation
  modes. Directory errors refuse new Company work with HTTP 503.
- Eight real MongoDB retention cases: both Mongo adapters paired with all four
  SQL Company stores. Refresh removes old completed automation history, retains
  recent/incomplete/other-schedule rows, and continues to completion proposals.
- Two synchronous attention cases inside an event loop, on SQLite and PostgreSQL,
  with empty and paginated histories, product filtering and stale-failure removal.

The prior actor/owner, authorization, recovery-error and failure-streak matrices
remain in the complete integration selection.

**Result:** All four disjoint partitions passed 436 cases each on implementation
`51b03980c696c296a1780b31dad20001c2c1b561` (259.39, 262.49, 274.26 and 279.01
seconds). Both PostgreSQL and MongoDB were explicitly enabled. A separate clean
run of all 50 new regression cases passed in 73.98 seconds. These final runs
supersede the earlier development runs and prior-head validation.

The full Company integration tree was collected once and partitioned into four
disjoint runs. It includes every `test_company_*.py`, Product/Project/Task and
schedule lifecycle parity suites, and the SQLite Product/Project/Task suites.
The four Company adapters are sync SQLite, async SQLite, sync PostgreSQL and
async PostgreSQL. PostgreSQL used the local service on port 5532; MongoDB used port 27017.

The new ownership and recovery suite covers:

- Alice's first attempt and Bob's revision on the same Alice-owned session,
  with `started_by` retaining the human actor. Agent, Team and Workflow routes
  run in both isolation modes, with token scopes and managed roles.
- Missing executor run permission returns 403. Automatic pickup retains the
  accepting human as actor while keeping the Task owner as the run user.
- Legacy starter-owned reservations and queue tickets recover with their
  recorded identity. A subsequent attempt adopts the idle session only after
  matching its original reservation and run. Unrelated session owners return 404.
- Paused Routines and revoked policies do not prevent existing-attempt cleanup
  or completed-result projection. Recovery is fenced against enqueueing.
- Ticketless Pending attempts are cancelled. Running attempts remain observable
  until durable completion or explicit cancellation; registry absence alone is
  not authoritative liveness evidence. Missing ticket-and-run reservations receive a
  cancelled Task result and can start a new numbered attempt.
- Concurrent worker projection and recovery settle once. Competing completed,
  failed and cancelled terminal results preserve exactly one winner.
- Repeated identical dispatch errors retain one failed history row with a
  count, including failure immediately after automatic acceptance. A new reason
  or Task move resets the count; attention drops stale failures.
- Refresh applies configured 7-day and default 30-day automation retention,
  preserving recent and unfinished rows, through the actual Company tool.

Reproduce the integration selection with the development Python and
`PYTHONPATH=libs/agno`:

```bash
.venv/bin/python -m pytest \
  libs/agno/tests/integration/db/test_company_*.py \
  libs/agno/tests/integration/db/test_{products,projects,tasks,schedule}_lifecycle_parity.py \
  libs/agno/tests/integration/db/sqlite/test_{products,projects,tasks}.py \
  -q --disable-warnings --tb=short -o log_cli=false
```

Set `AGNO_TEST_POSTGRES_URL` and `AGNO_TEST_MONGO_URL` to the local services to
include optional schedule lifecycle and MongoDB cases. The Company PostgreSQL
fixtures already configure the local service.

## Unit validation

**Status:** PASS — 6,458 tests, 39 conditional skips, no failures.

**Description:** Reran the complete database, OS (including authorization),
scheduler and Company-tool suites on the review-fix implementation.

**Result:** All selected unit suites passed in 536.61 seconds. The command was:

```bash
.venv/bin/python -m pytest \
  libs/agno/tests/unit/db libs/agno/tests/unit/os \
  libs/agno/tests/unit/scheduler libs/agno/tests/unit/tools/test_company.py \
  -q --disable-warnings --tb=short -o log_cli=false
```

## Cookbook validation

**Status:** PASS — all 15 invocations on the review-fix implementation.

All paths below are relative to `cookbook/05_agent_os/30_company/`. Each example
was executed using the development Python with this worktree's framework on
`PYTHONPATH`. These use deterministic local components and make no model calls.

| Test | Modes | Description and result |
| --- | --- | --- |
| `01_manage_products.py` | SQLite | PASS: ownership filters, archive and restore assertions. |
| `02_manage_projects.py` | SQLite | PASS: collaborative Project lifecycle and ownership. |
| `03_manage_tasks.py` | SQLite | PASS: acceptance, frozen scope, transitions and restore. |
| `04_manage_playbook.py` | SQLite | PASS: sync/async wiki, version conflicts and decisions. |
| `05_product_manager.py` | SQLite | PASS: model resolution, bounded tools and MCP setup without inference. |
| `06_execute_tasks.py` | SQLite and PostgreSQL, manual and automatic | PASS in all four modes: durable execution, duplicate start, result and attention assertions. |
| `07_cascading_archive.py` | SQLite and `--postgres` | PASS in both modes: active-work refusal, cascading archive and exact restore. |
| `07_heartbeat.py` | SQLite | PASS: declarations, Source evidence, Routine persistence and duplicate-free intake. |
| `08_custom_routines.py` | SQLite | PASS: custom Routine and discovered website Source configuration. |
| `09_task_session_ownership.py` | SQLite and PostgreSQL | PASS in both modes: Alice/Bob attempts share one Alice-owned session and retain separate actor attribution. |

For execution examples, `COMPANY_DB=postgres` selects PostgreSQL session and
Company storage; their durable queue uses PostgreSQL in both modes.
`COMPANY_AUTOMATION=1` selects automatic execution in `06_execute_tasks.py`.

## Format, validation and scope

**Status:** PASS

Full repository `./scripts/format.sh` and `./scripts/validate.sh` run with the clean
Python 3.10 validation environment. The full formatter also normalizes existing
import ordering and wrapping in twelve unrelated files; those edits are mechanical.
No executor enum, Source type or sandbox acceptance behavior is changed here.

**Result:** Full Ruff formatting/import sorting and lint passed. Mypy passed for
1,182 framework files and 21 CLI files. The cookbook pattern check passed all 13
checked quickstart files with no violations. `git diff --check` passed.

These are local tests, not CI, independent review or hosted deployment evidence.
No paid model calls or real outbound notification deliveries were exercised.


### 09_sandboxed_engineers.py

**Status:** PASS

**Description:** Ran `PYTHONPATH=libs/agno .venv/bin/python cookbook/05_agent_os/30_company/09_sandboxed_engineers.py --config-only` on October 16, 2026. Both ClaudeAgent and CodexAgent accept the repository, isolated Docker network, explicit checkpoint store, workspace size and execution timeout configuration.

**Result:** Configuration smoke passed without model calls. The credential-free sandbox fixture separately exercised real public GitHub checkout, Task pin projection, container replacement, attempt-two session reuse, concurrent admission and acceptance on sync/async SQLite and PostgreSQL Company stores. The Claude and Codex model turns were not run.

---

### Sandboxed Company executor regression checks

**Status:** PASS

**Description:** October 16, 2026: all 1,344 Company integration cases passed across synchronous and asynchronous SQLite and PostgreSQL (eight conditional Mongo cases skipped). The affected unit suites passed 3,417 tests (35 conditional skips). All 12 Company Docker fixture cases passed, including cancellation during submission, and all 25 existing AgentOS sandbox cases passed, including the opt-in public-repository case. The Docker fixture used PostgreSQL, Redis and `agno-sandbox:pr71-repository`; no Claude or Codex model turn was invoked.

**Result:** Full format and validation scripts passed; validation used the clean Python 3.10 environment. These are local checks, not CI or independent review. PR 6.6 integration remains pending: its recovery completion must share the checkout projection before recovered sandbox completions can be claimed as covered.

---

### PR 7.2 review fixes — retry pins and live execution admission

**Status:** PASS

**Description:** Failed or cancelled first attempts no longer prevent a later successful attempt from storing the checkout pin. Admission reads live queue tickets using their recorded executor, including after Backlog return, reassignment, archival, or a newer Task reservation; a retained run still blocks when its ticket is missing. Added four-adapter regressions for both blockers and for authorization before admission. External agents are refused as team members, Windows/UNC local git paths remain valid, legacy Source references can be edited without replacement, and an explicit read-token Source requires `GITHUB_READ_TOKEN` in the sandbox environment.

**Result:** 1,751 affected unit tests passed (35 conditional skips), all 12 Company Docker cases passed, and the focused review suite passed 170 tests. The broad Company integration run passed 1,368 cases with eight conditional Mongo skips; its 16 failures exposed executor validation occurring after endpoint construction in the permission cleanup. That order was corrected, and all 16 failed cases passed on rerun, giving 1,384 distinct passing Company cases. A further final-source focused route run passed all 88 cases. Full format, clean Python 3.10 validation and whitespace checks passed. No paid model turns were run. PR 6.6 recovery integration remains deferred until it merges.

---

### PR 7.2 second review — admission and retries

**Status:** PASS

**Description:** Settled historical attempts are excluded before resolving retired run stores. Live-ticket enumeration propagates failures for admission, includes untagged jobs claimed by named deployments, and uses the existing quiet-contention response for automatic pickup. Checkout validation errors can retry after their cause is repaired. Acceptance refuses a repository or branch incompatible with an established checkout.

**Result:** All 96 focused regressions passed across sync/async SQLite and PostgreSQL. The affected unit suite passed 1,751 tests (35 conditional skips); all 12 Company Docker cases and all 183 queue-store parity cases passed. All 1,428 Company integration cases passed, with eight conditional Mongo skips. Full format, clean Python 3.10 validation and whitespace checks passed. No paid model turns were run. PR 6.6 dispatch and recovery functions remain unchanged; recovery pin integration is deferred until that PR merges.

---

### PR 7.2 rebase and overlapping deployment admission

**Status:** PASS

**Description:** Rebased onto the latest PR 6.6 head, `f238e6892a9cfd634363fd0c41dfcb6c668fee3f`. Preserved its authenticated internal transport and passed the trusted checkout metadata through that application path. Admission uses a common advisory lock because named workers can claim untagged jobs. A deterministic two-application regression reproduced two accepted starts in all eight adapter/ordering cases before the fix; all eight now admit one start and refuse the other.

**Result:** All 104 focused regressions passed across sync/async SQLite and PostgreSQL. The affected unit suite passed 1,751 tests (35 conditional skips); all 12 Docker and 183 queue-store parity cases passed. Cookbook configuration smoke, full format, clean Python 3.10 validation and whitespace checks passed. The initial combined run passed 1,840 cases and exposed four recovery-test failures caused by this module leaving Redis process defaults attached to a closed test event loop. The fixture now restores those defaults; all 24 ordered concurrent-start/recovery cases pass. A clean 1,844-case combined rerun is in progress at publication; its final results are recorded in the PR. No paid model calls. Recovery checkout projection remains deferred until PR 6.6 merges.

---

### PR 7.2 recovery checkout integration

**Status:** PASS

**Description:** Merged main after PR 6.6 landed, using normal merge commit `4554646f1e`. Recovered completed runs now use the same checkout projection as worker completion. The first successful recovery stores the pin, later attempts verify it, missing or changed pins fail the attempt, and an unavailable sandbox executor leaves recovery retryable. The checkout and result use the existing guarded atomic completion write; a stale recovery cannot replace a settled winner.

**Result:** All 20 recovery regressions passed across sync/async SQLite and PostgreSQL. The complete Company/lifecycle matrix passed 1,864 cases with PostgreSQL and MongoDB enabled and no skips. The affected unit suite passed 1,751 tests (35 conditional skips); all 12 Docker and 183 queue-store parity cases passed. Cookbook configuration smoke, full format, clean Python 3.10 validation and whitespace checks passed. No paid model calls. These are local results; CI and independent review remain separate.

---

### PR 7.2 pinned Task acceptance consistency

**Status:** PASS

**Description:** Sync and async acceptance now reject a pinned Task's reassignment to a non-sandboxed agent, team or workflow with HTTP 409. Unpinned Tasks retain their existing behavior. The four-adapter regression covers refusal without mutation and successful session/pin reuse and recovery after selecting a compatible sandboxed executor. All 12 pinned cases failed before the fix; all 24 pinned/unpinned cases pass afterward.

**Result:** All 148 focused sandbox/checkout tests, 1,751 affected unit tests (35 conditional skips), and 12 Docker cases passed. The broad Company/lifecycle run passed 1,886 cases and exposed two async concurrency fixtures pausing at the new preliminary validation read rather than the intended SQL transition read. The fixture now pauses within the transition transaction; the complete 40-case Task lifecycle suite passed on rerun, yielding 1,888 distinct passing integration cases. Full format, clean Python 3.10 validation, cookbook configuration smoke and whitespace checks passed. No paid model calls. Recovery and queue admission production code are unchanged.

---

### PR 7.2 unreleased migration cleanup

**Status:** PASS

**Description:** Removed the unreleased Company Task migration, its version registration, migration-specific tests and upgrade instructions. Task schema mismatches no longer recommend an unavailable migration. PostgreSQL and SQLite initial schemas still include checkout metadata; pin projection, acceptance and recovery behavior are unchanged.

**Result:** All 1,084 affected Company checkout, admission, lifecycle, execution and recovery integration cases passed across sync/async SQLite and PostgreSQL. All seven migration endpoint cases and 12 real Docker Company cases passed. The database/OS unit run passed 6,241 cases with 39 skips; eight Redis cases failed, including teardown, after the shared Redis service disappeared. All 19 cases in that module passed against temporary Redis, yielding 6,249 distinct unit passes. The initial integration run was interrupted after the shared PostgreSQL service disappeared; the complete four-process rerun passed against a disposable database. Full format, clean Python 3.10 validation, cookbook configuration smoke and whitespace checks passed. The shared development environment reports 40 mypy diagnostics in untouched files; clean validation reports none. No model calls were made for this cleanup.

---

### PR 7.2 queue listing API cleanup

**Status:** PASS

**Description:** Moved `sandboxed` to the end of `AgentResponse`. Renamed the PostgreSQL queue listing flag to `raise_on_error`, updated Company admission, and accepted the same keyword on Redis and in-memory stores. Explicit error propagation works across all built-in stores; PostgreSQL retains its default fallback, while Redis and in-memory retain their existing error propagation.

**Result:** All 164 focused queue and sandbox unit cases and all 309 queue-store parity/Company admission integration cases passed, with no skips. New coverage checks errors across sync/async PostgreSQL, Redis and in-memory stores, and matching listing results with both flag values on in-memory, fake/real Redis and sync/async PostgreSQL. Full format, clean Python 3.10 validation and whitespace checks passed. No model calls were made.

---

### 10_weekly_product_review.py — framework manager Routine executors (2026-10-20)

**Status:** PASS

**Description:** Checked the opt-in weekly Product Manager review with OS Manager disabled and enabled using `--check` and `--check --with-os-manager`. Both construct and persist the owned-manager schedule without running a model. Offline scripted-model tests exercise bootstrap, API and human chat configuration, native/Studio delegation, queued execution, caller permissions, Product restrictions, private run ownership, reserved-ID collisions, evidence-backed intake, deduplication and versioned status updates.

**Result:** On main base `cb14cab365`, all 1,059 affected unit cases passed, including the 69 manager Routine cases; those 69 also passed in a clean Python 3.10 environment. All 409 selected existing Routine/heartbeat/automatic-execution integration cases passed. The new manager queue/configuration tests and existing chat tests passed 176 cases, with 52 unsupported synchronous-tool/asynchronous-database combinations skipped. The 18 supported chat cases passed again after isolating their schedule database fixture. Integration coverage uses sync/async SQLite and PostgreSQL Company stores and a real PostgreSQL durable worker. Full format, clean CI-dependency validation and whitespace checks passed. The shared Python 3.12 environment's nine mypy diagnostics also reproduce on the unchanged original base; the clean validation gate has none. No paid model calls. Live proposal quality and semantic duplicate detection are not evaluated by scripted responses.

---

### 10_weekly_product_review.py — Routine result recovery follow-up (2026-10-20)

**Status:** PASS

**Description:** Rechecked both `--check` configurations after correcting Routine result reporting. Regression tests verify that a status version conflict can recover through a confirmed later write to the same Product, while denied writes and unresolved conflicts remain failures. Native and Studio delegation report provider failures, and nested failed or cancelled member results remain failures.

**Result:** All 82 manager Routine tests passed on Python 3.12 and Python 3.10, including 13 new regression cases; seven new cases failed before the fix. Another 729 Company, manager and scheduler unit cases passed. SQLite chat integration passed nine cases, with three unsupported synchronous-tool/asynchronous-database cases skipped. Both cookbook checks, the full format script, clean Python 3.10 validation and whitespace checks passed. Formatting-only changes to two unrelated baseline files were excluded. PostgreSQL queue integration was not rerun for this follow-up. No paid model calls.

---

### 05_company_manager.py and 10_weekly_product_review.py — Company Manager rename and Routine executor rule (2026-10-20)

**Status:** PASS

**Description:** Product Manager is renamed Company Manager (`company-manager-internal`); `product-manager-internal` stays reserved and `AgentOS.product_manager` is a deprecated alias. Company Manager is the only framework manager that can execute a Routine. Ran `05_company_manager.py`, `10_weekly_product_review.py --check` and `--check --with-os-manager`.

**Result:** All three runs passed without model calls; both weekly variants persist `/agents/company-manager-internal/runs`. Offline tests cover refusal of OS Manager, both specialists and the legacy id through the endpoint resolver, bootstrap, the Routine API and human chat tools, with no partial Product written.

---

### 05_company_manager.py and 10_weekly_product_review.py — merge with main and separate manager member (2026-10-21)

**Status:** PASS

**Description:** Merged main (Routine linkage and ownership, OS Manager tool budgets) into the Company Manager Routine branch. With OS Manager enabled, the team now holds its own Company Manager member carrying `member_tool_call_limit` and focused instructions, while the served Company Manager used by chat and Routines keeps its standalone policy. Ran `05_company_manager.py`, `10_weekly_product_review.py --check` and `--check --with-os-manager`.

**Result:** All three runs passed without model calls. A new regression case fails when the member and served agent are the same object (the served agent inherits the member limit) and passes with separate instances.

---

### 05_company_manager.py — Product tool names (2026-10-22)

**Status:** PASS

**Description:** Ran the offline Company Manager example with `update_product_status`.

**Result:** Saved the Backlog proposal, Product status and decision; no model calls.

---

### 08_custom_routines.py — Product tool names (2026-10-22)

**Status:** PASS

**Description:** Ran the offline custom Routine example with `add_product_source`.

**Result:** Repeated website discovery reused the same attributed Source; Routine controls and Source archival passed without model calls or website requests.

---

### 10_weekly_product_review.py — Product tool names (2026-10-22)

**Status:** PASS

**Description:** Updated review instructions to `read_product_source` and `intake_product_source`; ran `--check` and `--check --with-os-manager`.

**Result:** Both configurations persisted the Company Manager Routine with automatic acceptance disabled. These checks validate configuration; they do not execute a review or make model calls.

---
