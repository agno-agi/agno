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

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
