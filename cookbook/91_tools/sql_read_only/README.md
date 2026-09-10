# Read-only SQL desk

The former Metrics Desk example is preserved here because its SQLite driver mode
and authorizer demonstrate protections absent from the basic SQLTools example.
It is no longer part of the featured agent collection.

From the repository root, with the cookbook demo environment set up:

```bash
export OPENAI_API_KEY="your-openai-api-key"
cd cookbook/91_tools/sql_read_only
../../../.venvs/demo/bin/python demo.py
```

The demo seeds five fictional orders in `tmp/shop.db`, measures totals, attempts
a write, and verifies the rows remain. SQLite `mode=ro` rejects writes; an
authorizer rejects ATTACH/DETACH and temporary schema creation. The model receives
SQL results, so this is not a promise that rows stay off the provider's servers.
Runtime data and sessions live under `tmp/`; use an isolated working directory.

`metrics_desk.py` serves a local unauthenticated AgentOS/MCP demo bound to
127.0.0.1. Do not expose it remotely without authentication. Real production
access needs read-only database credentials and database-specific permissions.

See [TEST_LOG.md](TEST_LOG.md) for current validation and historical runs.
