# Test Log: 12_scheduler

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
claimed schedule `a1fce037-00a5-4b90-a7a0-2cc9d1410e93` at the next minute.
The executor completed Agent run
`0593890f-411b-4622-ae4b-9c931eafe768`, and persisted schedule-run
`3d977877-5d07-455e-bc11-b45a11c078d4` with status `success`.

---

### 02_rest_api.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran raw REST CRUD, state changes, two manual triggers, and
two pages of persisted history against the live scheduler server.

**Result:** `GET /health` returned `ok`; `GET /config` returned
`scheduler-agent-os` and `scheduled-greeter`. Create, list, detail, PATCH from
`0 0 1 1 *` to `0 9 1 1 *`, disable, enable, trigger, history, and delete all
succeeded. Trigger records `f3971733-0cfb-4fb1-9c4d-2334174d9bbf` and
`70e619ba-7868-4665-9d5a-3dde8d27d57d` appeared on distinct `page=1` and
`page=2` responses with exact top-level keys `data` and `meta`.

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
`e8f217cc-47cc-4df8-a701-08bfb4cdba3c`.

---

### 04_scheduler_tools_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the SchedulerTools AgentOS and asked the live
`gpt-5.5` agent to create a schedule using configured defaults.

**Result:** `GET /health` returned `ok`; `GET /config` returned
`scheduler-tools-agent-os` and `scheduler-tools-agent`. Agent run
`874d2d5c-73cb-4839-9c67-313ec85dec0c` called the narrowed SchedulerTools
create schema once. Stored schedule `c3499a5d-b51d-41b8-bed7-b7c08a89b24d`
had cron `0 9 * * *`, timezone `UTC`, endpoint
`/agents/scheduler-tools-agent/runs`, and the exact configured default payload.

---

## Validation

- All four runnable files completed with exit status 0.
- Both scheduler-enabled apps shut down cleanly with no stranded listener.
- Recursive pattern validation checked exactly 4 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Python compilation, stale-model, deprecated-surface, scope, Unicode/emoji,
  non-PASS status, and `git diff --check` gates passed.
