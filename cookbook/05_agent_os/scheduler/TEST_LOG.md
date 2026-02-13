# Test Log — scheduler/

### basic_schedule.py

**Status:** PASS

**Description:** AgentOS server with `scheduler=True` and a simple greeter agent. Schedules created via REST API after server starts.

**Result:** Import and app construction OK.

---

### async_schedule.py

**Status:** FAIL

**Description:** Async ScheduleManager API demo (acreate, alist, aget, aupdate, adelete, aenable, adisable). Uses SqliteDb and Rich console output.

**Result:** `TypeError: SqliteDb.get_schedules() got an unexpected keyword argument 'offset'`. Framework bug: ScheduleManager.list() passes `offset=` but DB adapters expect `page=`.

---

### demo.py

**Status:** PASS

**Description:** AgentOS with programmatic schedule creation via ScheduleManager. Uses `if_exists="update"` for idempotent re-runs. Two agents with schedules polled automatically.

**Result:** Import and app construction OK. Schedules created programmatically.

---

### multi_agent_schedules.py

**Status:** FAIL

**Description:** Multiple agents with different cron patterns, timezones, retry configs, and Rich console display. Demonstrates filtered views.

**Result:** Same framework bug: `offset` parameter mismatch on `get_schedules()`.

---

### rest_api_schedules.py

**Status:** SKIP

**Description:** REST API client demonstrating full CRUD lifecycle on schedule endpoints. Requires a running server at localhost:7777.

**Result:** Syntax and imports validated. Runtime requires running AgentOS server.

---

### run_history.py

**Status:** FAIL

**Description:** Schedule run history display with simulated run records, Rich tables, and pagination.

**Result:** Same framework bug: `offset` parameter mismatch on `get_schedule_runs()`.

---

### schedule_management.py

**Status:** SKIP

**Description:** REST API client for schedule management (create, list, update, disable, enable, trigger, delete). Requires running server.

**Result:** Syntax and imports validated. Runtime requires running AgentOS server.

---

### schedule_validation.py

**Status:** FAIL

**Description:** Validation and error handling: invalid cron, invalid timezone, duplicates, complex patterns, method auto-uppercasing.

**Result:** Same framework bug: `offset` parameter mismatch on `get_schedules()`.

---

### scheduler_with_agentos.py

**Status:** PASS

**Description:** Primary AgentOS scheduler DX. `scheduler=True` registers `/schedules` endpoints, starts poller on startup, generates internal service token.

**Result:** Import and app construction OK.

---

### team_workflow_schedules.py

**Status:** FAIL

**Description:** Scheduling teams and workflows (not just agents). Different HTTP methods for non-run endpoints.

**Result:** Same framework bug: `offset` parameter mismatch on `get_schedules()`.

---
