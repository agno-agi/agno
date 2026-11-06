# Test log

### managed_lifecycle.py

**Status:** PASS

**Description:** Ran against a dedicated local PostgreSQL database with offline deterministic coordinator, worker and assessor models. The actual Company Manager API created and accepted work, the durable queue ran the artifact-writing executor, and an assessment requested one revision on the same Task/session before completing both Task and Project. An unrelated conversation turn completed before execution. No human lifecycle approvals or paid model calls.

**Result:** Two worker attempts, Task Done, Project Done; isolated schema cleaned up. Run on 2026-11-06 with `PYTHONPATH=libs/agno DATABASE_URL=postgresql+psycopg://agno:agno@localhost:5532/agno .venv/bin/python cookbook/05_agent_os/30_company/14_managed_lifecycle/managed_lifecycle.py`.

---

### Lifecycle regression tests

**Status:** PASS

**Description:** Twenty actual API/PostgreSQL scenarios cover managed-role authorization, permission denial/revocation, one revision, exhausted limits, fabricated evidence references, missing input, fresh-scheduler recovery, cancellation during assessment, duplicate intake, responsive status while a worker is running, same-second scope changes, disabled principals and fail-closed user-directory outages. Thirteen unit checks cover trusted provenance, manual override, stale histories/briefs, Project assessment authority and revision instructions ending at the latest acceptance boundary.

**Result:** 20 PostgreSQL integration tests and 13 unit tests passed; 168 existing Company execution/Routine tests also passed. Live provider quality, hosted deployment and multi-host fault injection were not exercised.
