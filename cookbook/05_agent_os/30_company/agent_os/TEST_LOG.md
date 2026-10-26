# Company AgentOS Servers Test Log

October 21, 2026. Each server was started with `.venv/bin/python`, with
`JWT_VERIFICATION_KEY` and `AGNO_SECURITY_KEY` unset, and probed over HTTP.
PostgreSQL ran on localhost:5532. No model calls were made.

### 01_manage_products.py

**Status:** PASS

**Description:** Listed both seeded Products with owners, deleted `sdk` (204), saw one Product remain, then restored it.

**Result:** Archive and restore work over HTTP.

---

### 02_manage_projects.py

**Status:** PASS

**Description:** `GET /company/projects` returned the proposed Bob Project and the done Alice Project.

**Result:** Seeded lifecycle served.

---

### 03_manage_tasks.py

**Status:** PASS

**Description:** `GET /company/tasks` returned both Backlog Tasks; `writer` is registered as an executor.

**Result:** Seeded Tasks served.

---

### 04_manage_playbook.py

**Status:** PASS

**Description:** `GET /company/wiki` listed `brief.md` and `status.md`; `GET /company/decisions` returned the seeded decision.

**Result:** Playbook served.

---

### 05_product_manager.py

**Status:** PASS

**Description:** `GET /agents` listed `intake-reader` with Company tools; the Product list starts empty for chat to fill.

**Result:** Server starts. Product Manager chat was not exercised (needs a model call).

---

### 06_execute_tasks.py

**Status:** PASS

**Description:** Accepted the seeded Task for the `draft` workflow, started run attempt 1 (202, PENDING), and polled.

**Result:** Task reached `in_review` with "Draft ready for review: Summarize reviewed changes".

---

### 07_cascading_archive.py

**Status:** PASS

**Description:** `GET /company/tasks?include_deleted=true` returned the Ready `Write guide` Task accepted for `writer`.

**Result:** Seeded hierarchy served.

---

### 07_heartbeat.py

**Status:** PASS

**Description:** `GET /company/routines` returned `documentation.intake` targeting `source-reader`; `GET /company/sources` returned the markdown Source.

**Result:** Declared Product, Source and Routine bootstrapped. Trigger not exercised (needs a model call).

---

### 08_custom_routines.py

**Status:** PASS

**Description:** `GET /company/routines` returned the template-free `research.watch` Routine for `researcher`.

**Result:** Declared Routine bootstrapped. Trigger not exercised (needs a model call).

---

### 09_sandboxed_engineers.py

**Status:** PASS

**Description:** Server started and `GET /company/tasks` returned the Backlog `Inspect README` Task.

**Result:** Startup and seeding only. Sandboxed runs not exercised: Redis on 6379 and the sandbox image were not available.

---

### 09_task_session_ownership.py

**Status:** PASS

**Description:** With Alice's printed bearer token, `GET /company/tasks` returned her Ready Task accepted for `draft`.

**Result:** JWT authorization and seeding work. The two-attempt run flow was not repeated over HTTP.

---

### 01_manage_products.py — temporary workflow run (22 October 2026)

**Status:** PASS

**Description:** Restarted the existing Company AgentOS on port 7777 with PR #11163. Configuration reports `allow_temporary_runs=true`. Submitted a streamed `company-draft` run with `store_run=false` and `background=false` using a unique test session ID.

**Result:** HTTP 200 with `WorkflowCompleted`; fetching the session returned 404, confirming no session was saved. The backend temporary-run unit tests also passed (56 tests). Model-backed agent/team runs were not exercised; the launch environment has no `OPENAI_API_KEY`.

---
