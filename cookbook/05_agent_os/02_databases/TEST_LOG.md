# Test Log: 02_databases

Tested on 2026-07-24 against Agno source commit
`64129408633bb3f4837b2a09a0eb087eddbed86a`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS with a default SQLite database and an agent
that intentionally omits its own database, then exercised live health,
configuration, session-write, and session-list endpoints.

**Result:** Startup provisioned the AgentOS tables. `/config` reported
`agent-os-default-db` for both the OS and `database-agent`. A session created
through `POST /sessions` was read back from `GET /sessions`.

---

### postgres.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the same AgentOS server against a live Postgres service on
port 5532 in both synchronous and asynchronous adapter modes, exercising
health, configuration, session-write, and session-list endpoints in each mode.

**Result:** The synchronous run provisioned its schema and reported database
`agent-os-postgres-sync`; the asynchronous run reported
`agent-os-postgres-async`. Each adapter persisted and returned its own test
session.

---

### surreal.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started an isolated live SurrealDB service, configured the
example through `SURREALDB_URL`, then exercised health, configuration,
session-write, and session-list endpoints.

**Result:** `/config` reported database `agent-os-surreal` for the OS and
`surreal-agent`. A session created through `POST /sessions` was successfully
read back from SurrealDB. The isolated service used port 8001 because port 8000
was already owned by another local AgentOS container.

---
