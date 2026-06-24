# Tracing DBs Cookbook

Examples for `tracing/dbs` in AgentOS.

## Files
- `basic_agent_with_postgresdb.py` — Tracing with a production-oriented relational backend.
- `basic_agent_with_sqlite.py` — Tracing with a lightweight local development backend.
- `basic_agent_with_mongodb.py` — Tracing with a document database backend.

## Supported Backends
- The tracing pattern is the same across database backends: the agent setup is unchanged and only the DB adapter import/config differs.
- Representative examples are kept for Postgres, SQLite, and MongoDB.
- Other supported backends in the original set: Async MySQL, Async Postgres, Async SQLite, DynamoDB, Firestore, GCS JSON DB, JSON DB, MySQL, Redis, SingleStore, and SurrealDB.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, MongoDB, or SQLite).
