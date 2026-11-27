# Test Log: 12_scheduler

Re-verified LIVE on 2026-11-27 against worktree commit `3e0971a9d` (branch
`feat/eval-suite-routes`) with scheduled eval suites added. All five runnable
files pass against live Postgres: `01_run_in_agentos.py` fired naturally and
recorded a `success` run;
`02_rest_api.py` triggered 2 runs, both `success`, across 2 history pages;
`03_manage_with_python.py` exercised the sync and async managers with 3
validation errors; `04_scheduler_tools_agent.py --demo` had the agent create
a schedule on `/agents/scheduler-tools-agent/runs`; and
`05_schedule_eval_suite.py` fired naturally and ran the suite to PASS.

Re-verified LIVE on 2026-08-18 against worktree commit `9ea0b121a`
(branch `feat/studio-3.0`) after the schedules table gained Studio 3.0
provenance columns (`managed_by`, `target_type`/`target_id`, actor stamps,
`disabled_reason`) and `update_schedule` gained its column allow-list. All
four examples pass unchanged against live pgvector Postgres:
`03_manage_with_python.py` exercised sync + async managers (create, cron
update, paging, 3 validation errors); `01_run_in_agentos.py` +
`02_rest_api.py` covered the REST surface including trigger and history
paging (2 runs recorded); `04_scheduler_tools_agent.py --demo` had the live
agent create a schedule preserving the toolkit's default endpoint and
payload. These generic schedules carry no provenance, which is the
compatibility contract the migration must keep.

Original pass on 2026-07-24 against Agno source commit
`74c0bfb1499c2636aa7c3f1ccd8935ceeb824b4b`.

### 01_run_in_agentos.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the Postgres-backed AgentOS poller and ran the
checked-in observer through a naturally due minute.

**Result:** `GET /health` returned `ok`; `GET /config` returned
`scheduler-agent-os` and `scheduled-greeter`. The five-second poller naturally
claimed schedule `8070cbe2-2c87-43da-9db8-d7ebc441863b` at the next minute.
The executor completed Agent run
`126ea65f-2330-4677-9722-a8ee37692754`, and persisted schedule-run
`sr_01795769581969044000_c9a50f85-53f6-41a0-9e45-d8229059b196` with status
`success`.

---

### 02_rest_api.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran raw REST CRUD, state changes, two manual triggers, and
two pages of persisted history against the live scheduler server.

**Result:** `GET /health` returned `ok`; `GET /config` returned
`scheduler-agent-os` and `scheduled-greeter`. Create, list, detail, PATCH from
`0 0 1 1 *` to `0 9 1 1 *`, disable, enable, trigger, history, and delete all
succeeded. Trigger records
`sr_01795769616713209000_e7cf4dfd-0e32-4fde-b743-0ce6870e48ef` and
`sr_01795769646766519000_5616f789-6599-4eab-9fbc-2f26ce66f09c` appeared on
distinct `page=1` and `page=2` responses with exact top-level keys `data` and
`meta`.

---

### 03_manage_with_python.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran synchronous and asynchronous ScheduleManager operations
against the live Postgres service.

**Result:** The sync path created Agent, Team, and Workflow schedules; returned
two rows on `page=1` and one on `page=2`; persisted a `cron_expr` update;
recomputed `next_run_at` on enable; and caught cron, timezone, and
duplicate-name errors. The real `AsyncPostgresDb` path created, listed,
fetched, disabled, updated, enabled, paged history, and deleted schedule
`74e97331-adf2-4c36-91ab-ab9ac4546431`.

---

### 04_scheduler_tools_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the SchedulerTools AgentOS and asked the live
`gpt-5.5` agent to create a schedule using configured defaults.

**Result:** `GET /health` returned `ok`; `GET /config` returned
`scheduler-tools-agent-os` and `scheduler-tools-agent`. Agent run
`14cb4052-6483-4745-857a-548ca08e13c9` called the narrowed SchedulerTools
create schema once. Stored schedule `4ea2e491-a874-4abf-a5b6-0c8f28fbd8af`
had cron `0 9 * * *`, timezone `UTC`, endpoint
`/agents/scheduler-tools-agent/runs`, and the exact configured default payload.

---

### 05_schedule_eval_suite.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the Postgres-backed AgentOS poller with the
`nightly-math-quality` suite registered and ran the checked-in observer through
a naturally due minute.

**Result:** The poller claimed the one-minute schedule
`e23b6bbe-6138-403f-877a-1776da61156e` at the next minute. Schedule run
`sr_01795769763012585000_b92b590e-47b1-4851-b375-a3253d683235` ended `success`
with no error, and its `run_id` `e4799102-ca13-42c2-a03c-959cc44d3a56` read
back from `GET /eval-runs/{run_id}` as a suite run with PASS, 2 of 2 cases
passed.

---

## Validation

- All five runnable files completed with exit status 0.
- The three scheduler-enabled apps (`01`, `04`, `05`) shut down cleanly with
  no stranded listener.
- Targeted Ruff format and check passed.
- Python compilation and `git diff --check` passed.
