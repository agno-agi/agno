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

### s3_media_storage.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS against a real S3 bucket, uploaded a CSV to a
run and asked the agent to generate one through
`POST /agents/media-storage-agent/runs`, then inspected the persisted run rows
and fetched both files back through the media route.

**Result:** Both runs completed and each `agno_runs` row carried a
`MediaReference` rather than base64 (3590 and 6867 bytes). The uploaded and the
generated CSV were written to S3 under the default `agno/agentos/files/`
prefix (77 and 82 bytes, `ContentType: text/csv`), and
`GET /sessions/{session_id}/media/{storage_key}` returned 200 with
`text/csv; charset=utf-8` and byte-identical content; `redirect=true` returned
a 307 to a freshly-signed URL.

---

### gcs_media_storage.py

**Status:** PASS

**Test mode:** STATIC

**Description:** Loaded the cookbook with a placeholder bucket and inspected the
constructed AgentOS application without making a Google Cloud request.

**Result:** The agent and AgentOS share the same `AsyncGCSMediaStorage` instance,
and the application exposes both the agent run route and the session media route.
Ruff formatting, lint, and Python compilation also passed. Live GCS upload and
retrieval require configured credentials and a real bucket.

---

### media_storage_delete.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS against a real S3 bucket, attached a text file to a run
through `POST /agents/media-delete-agent/runs`, read the session and the object back, then
deleted the session both without and with `delete_media=true`.

**Result:** Run returned 200 and uploaded one object under `agno/agentos/files/`. The session
row carried a `media_reference` and no base64.
`GET /sessions/{session_id}/media/{storage_key}` returned 200 with `text/plain; charset=utf-8`
and the exact 21 bytes; `redirect=true` returned 307. `DELETE /sessions/{session_id}` returned
204 and left the object in S3; the same delete with `delete_media=true` returned 204 and
removed it. The bucket was restored to its prior contents afterwards.

---
