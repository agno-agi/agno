# Test Log: dbs

> Tests not yet run. Run each file and update this log.

### agentos_default_db.py

**Status:** PENDING

**Description:** AgentOS Demo.

---

### dynamo.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with a DynamoDB database.

---

### firestore.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with a Firestore database.

---

### gcs_json.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with JSON files hosted in GCS as database.

---

### json_db.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with JSON files as database.

---

### mongo.py

**Status:** PENDING

**Description:** Mongo Database Backend.

---

### mysql.py

**Status:** PENDING

**Description:** MySQL Database Backend.

---

### neon.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with Neon as our database provider.

---

### postgres.py

**Status:** PENDING

**Description:** Postgres Database Backend.

---

### redis_db.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with Redis as database.

---

### singlestore.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with SingleStore as our database provider.

---

### sqlite.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with a SQLite database.

---

### supabase.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with Supabase as our database provider.

---

### surreal.py

**Status:** PENDING

**Description:** Example showing how to use AgentOS with SurrealDB as database.

---

### turso_db.py

**Status:** BLOCKED (Turso beta) — kept as draft, revisit at Turso full release.

**Description:** Example showing how to use AgentOS with a local Turso database (via the `pyturso` driver / new Turso engine, formerly "Limbo"). Named `turso_db.py` (not `turso.py`) to avoid shadowing `import turso`. Requires `pip install "pyturso[sqlalchemy]"` (or `pip install "agno[turso]"`); no Windows wheels (Linux/macOS/WSL only).

**Result:** The `TursoDb` session backend does not currently work under the AgentOS server because the Turso engine is still in **beta** and cannot handle the concurrent-write pattern AgentOS produces. After a run, Agno persists the session **and** (on background threads) user-memory, session summary, and metrics — i.e. several overlapping writers. Turso is **single-writer by default and returns `database is locked` immediately instead of waiting** (its `busy_timeout` is effectively ignored — see libsql-client-ts#288), and it does **not** support multi-process access to a database file (tursodatabase/turso#769). Serializing to a single connection (`pool_size=1`) and disabling the uvicorn reloader (`reload=False`) did not resolve it, because the overlapping in-process writes still contend and even the connection-reset `ROLLBACK` fails with `Busy`. The only sanctioned fix is Turso's MVCC mode (`PRAGMA journal_mode='mvcc'` + `BEGIN CONCURRENT` + application-level conflict/retry), which would require forking the shared `SqliteDb` transaction logic that `TursoDb` deliberately reuses — not worth doing for a beta engine. For context, we first built this on the older **libSQL** driver (`sqlalchemy-libsql` + `libsql-experimental`) and hit different blockers there too: `INSERT ... RETURNING` + partial fetch fails `COMMIT` with "cannot commit transaction - SQL statements in progress", the driver's `isolation_level` attribute is read-only (breaks SQLAlchemy AUTOCOMMIT), and it's deprecated. Migrating to the new `pyturso` engine fixed the `RETURNING`/`COMMIT` and isolation-level issues (native `RETURNING`/`ON CONFLICT` support), leaving only the single-writer locking limitation above. The **`TursoVector`** knowledge/vector backend, by contrast, works end-to-end because it is single-threaded (sequential ingest → search); note it is **vector-only** (the Turso engine has no FTS5, so no keyword/hybrid search, and no ANN index — search is exact/full-scan). Revisit `TursoDb` once Turso reaches a stable release with reliable concurrent writes or a working busy-timeout.

---
