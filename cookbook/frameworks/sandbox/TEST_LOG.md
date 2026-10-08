# Sandbox acceptance results

Tested locally on 2026-10-09, on top of the phase-two dependency at
`b4d0e44f1d50d2797fc8c40f693131a38f3fb7b6`. These are local results, not a hosted
provider qualification or a claim about GitHub CI. Runtime: Docker 29.6.2 on
Linux/aarch64, Python 3.12, Postgres 18, Redis 7, SQLAlchemy 2.0.52,
claude-agent-sdk 0.2.148 and openai-codex 0.162.0.

### verify.py

**Status:** PASS

**Description:** Built the reference runtime and control-plane images and ran the
real Docker Compose topology: two API replicas, shared Postgres/Redis, a local
Git remote and dynamically created session containers. The deterministic harness
made no model calls.

**Result:** All 11 assertions passed: checkpoint push, client disconnect plus API
restart during execution, cross-replica replay, foreground responses/streams,
conversation/workspace retention, cancellation while waiting for a busy session,
cross-replica cancellation, fresh-container retry after a kill, ERROR on exhausted
attempts with a failure reason, idle destruction/restoration, and session deletion
cleanup. The first test-client revision incorrectly used GET for the POST-only
resume endpoint; it was corrected before the passing run.

---

### verify_live.py

**Status:** PASS

**Description:** Two real Claude Haiku turns through different API replicas.
Turn one remembered a random fact and wrote a separate random value to a file.
The container was destroyed after its checkpoint; turn two ran in a new generation
and returned both the remembered fact and restored file contents.

**Result:** Passed twice, including after refreshing the phase-two persistence
fixes. Four completed model calls in total, each configured with a $2 SDK budget
and one queue attempt ($8 cumulative configured budget, below the approved $50).
Actual billed cost is unavailable because this adapter does not emit cost metrics.
An initial repeat was submitted before the API had finished restarting; the
client now waits for both health endpoints. No model call began on that failed
submission. Live Codex, live Claude cancellation, and hosted providers were not
exercised.

---

### libs/agno/tests/unit/sandbox/

**Status:** PASS

**Description:** 20 focused tests cover sync/async SQLite registry CAS, immutable
ownership, competing replicas, one execution per session, generation replacement,
token/session/attempt scope, duplicate dispatch, old-worker fencing, API shutdown
after handoff, Git restore, management scoping/redaction, deletion tombstones,
busy-session waiting/cancellation, synchronous dispatch, storage configuration,
Docker daemon failure versus container absence, OOM diagnostics, and preservation
of warning/stream-expiry fields in foreground streams.

**Result:** 20 passed. The stream-warning forwarding check was added after the
Docker scenario to cover custom fields introduced by the refreshed dependency.

---

### libs/agno/tests/integration/db/test_sandbox_store.py

**Status:** PASS

**Description:** Real PostgreSQL contract tests, once with PostgresDb and once
with AsyncPostgresDb. Each uses and drops its own schema. Eight concurrent inserts
produce one binding, eight replacements produce one CAS winner, ownership is
immutable, and handoff preserves the attempt while preventing the old owner from
heartbeating, retrying or settling it.

**Result:** 2 passed, including a repeat against the refreshed dependency.
Set `AGNO_SANDBOX_TEST_DB_URL` to a disposable database to rerun.

---

### Existing lifecycle and durable-queue regressions

**Status:** PASS

**Description:** Combined sandbox, external-agent, background-run, status
persistence, worker-owned save fencing, queue store/worker/startup/wiring,
zombie-gate and queue-pagination suites.

**Result:** 391 passed before the final isolated stream-warning regression was
added; that additional regression passed in the 20-test sandbox suite. The
combined run emitted an aiosqlite thread-cleanup warning and an AsyncMock warning
in existing test code; neither was a test failure.

---

### Repository formatting and validation

**Status:** PASS

**Description:** Required `./scripts/format.sh` and `./scripts/validate.sh` using
the development virtual environment. Unrelated formatter-only baseline changes
were restored before submission.

**Result:** Ruff, framework mypy, CLI mypy and cookbook pattern checks passed.

---

## Scope of the evidence

This establishes the local Docker control-plane/execution-plane lifecycle. It does
not establish production load capacity, hostile-tenant isolation, fleet-wide
quotas, private repository credential integration, hosted sandbox compatibility,
or container snapshots. Recovery is from Postgres transcripts and the last
successful Git checkpoint. Changes after that checkpoint remain disposable.
