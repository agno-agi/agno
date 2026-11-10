# Test Log: 13_observability

Tested on 2026-07-24 against Agno source commit
`74c0bfb1499c2636aa7c3f1ccd8935ceeb824b4b`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in traced AgentOS server on port 7777 and
queried its health, rendered configuration, and trace-filter schema.

**Result:** `GET /health` returned `ok`; `GET /config` reported
`observability-basic-os` with `traced-assistant`; and
`GET /traces/filter-schema` returned 13 filterable fields, including `status`
and `agent_id`.

---

### read_traces.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the same `gpt-5.5` agent once with `run()` and once with
`arun()`, then used the in-process AgentOS ASGI app to call `GET /traces` and
`GET /traces/{trace_id}`.

**Result:** The list route returned both run IDs. Sync trace
`7c0654559a9cda523d90d5a387f2593a` contained an `Agent.run` root and
`OpenAIResponses.invoke` child; async trace
`056e2307116108a6767632294ebf5fff` contained an `Agent.arun` root and
`OpenAIResponses.ainvoke` child. Both trees had two spans with status `OK`.

---

### filtering.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Generated traces from two live `gpt-5.5` agents, built an
`AND(status=OK, OR(agent_id=...))` expression, and used it through both
`SqliteDb.get_traces()` and `POST /traces/search`.

**Result:** The Python query and AgentOS search each returned exactly the two
expected agents. `GET /traces/filter-schema` returned 13 fields and logical
operators `AND` and `OR`.

---

### traces_to_clickhouse.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Installed `clickhouse-connect`, started an isolated
`clickhouse/clickhouse-server` container on HTTP port 18123 with ephemeral
storage, and ran the checked-in split-store example against it.

**Result:** Run `7481a48e-f812-4aeb-a644-83e83048d3b4` persisted session
`clickhouse-trace-session` in SQLite and batched trace
`d932cd95a2e71a840ef053707edc64f4` into ClickHouse. Selected readback with
`db_id=clickhouse-traces` returned a two-span `OK` tree; the same request
without `db_id` returned the expected 400 because both databases were
registered. The scoped container was removed after the run.

---

### metrics.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the metrics agent with persisted session state, called
`POST /metrics/refresh`, and read the stored daily result from `GET /metrics`.

**Result:** Refresh returned one aggregate for 2026-07-24. Readback reported
one agent run, one agent session, one user, and 42 total tokens.

---

## Validation

- All five runnable examples completed with live observed results.
- The basic server passed `/health`, `/config`, and trace-route discovery.
- Recursive pattern validation checked exactly 5 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Deprecated API, stale-model, non-final-status, emoji, and static-f-string
  scans returned no target hits.
- `git diff --check` passed for the lesson and the consumed legacy tree.
- The isolated ClickHouse container was removed and no lesson server remains.
