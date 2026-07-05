# Dbs Cookbook

Examples for `dbs` in AgentOS.

## Files
- `agentos_default_db.py` — AgentOS Demo.
- `dynamo.py` — Example showing how to use AgentOS with a DynamoDB database.
- `firestore.py` — Example showing how to use AgentOS with a Firestore database.
- `gcs_json.py` — Example showing how to use AgentOS with JSON files hosted in GCS as database.
- `json_db.py` — Example showing how to use AgentOS with JSON files as database.
- `mongo.py` — Mongo Database Backend.
- `mysql.py` — MySQL Database Backend.
- `neon.py` — Example showing how to use AgentOS with Neon as our database provider.
- `postgres.py` — Postgres Database Backend.
- `redis_db.py` — Example showing how to use AgentOS with Redis as database.
- `singlestore.py` — Example showing how to use AgentOS with SingleStore as our database provider.
- `sqlite.py` — Example showing how to use AgentOS with a SQLite database.
- `supabase.py` — Example showing how to use AgentOS with Supabase as our database provider.
- `surreal.py` — Example showing how to use AgentOS with SurrealDB as database.
- `turso_db.py` — Example showing how to use AgentOS with a local Turso database (pyturso). **Experimental / draft — does not currently work under the AgentOS server (see note below).**

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).

## Note on Turso (`turso_db.py`)
`TursoDb` is built on the new **`pyturso`** engine (formerly "Limbo"), which is still in **beta**, and is kept as a **draft**. It does **not** currently work as a session store under the AgentOS server: AgentOS writes the session plus user-memory/summary/metrics concurrently (on background threads), and Turso is single-writer by default — it returns `database is locked` immediately instead of waiting (its `busy_timeout` is ignored), and it does not support multi-process access to a database file ([tursodatabase/turso#769](https://github.com/tursodatabase/turso/issues/769)). Serializing to one connection and disabling the reloader does not resolve it; the only sanctioned fix (MVCC via `PRAGMA journal_mode='mvcc'` + `BEGIN CONCURRENT` + retry) would require forking the shared `SqliteDb` logic and isn't worth it for a beta engine. The `pyturso` package also ships no Windows wheels (Linux/macOS/WSL only). The Turso **vector store** (`cookbook/07_knowledge/05_integrations/vector_dbs/05_turso.py`) works, since it is single-threaded. Revisit `turso_db.py` when Turso reaches a stable release with reliable concurrent writes.
