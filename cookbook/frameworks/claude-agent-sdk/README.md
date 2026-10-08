# Claude Agent SDK

Use `ClaudeAgent` to run Claude Code through Agno and AgentOS. Install `claude-agent-sdk` and configure Claude authentication in your environment.

## Durable transcripts

`session_store.py --verify` starts two independent processes with separate empty `CLAUDE_CONFIG_DIR` directories. The first stores a fact and mirrors the Claude transcript to SQLite. Its Agno run history is removed so the second process must resume the SDK transcript from the database to recall the fact.

```bash
PYTHONPATH=libs/agno /Users/ab/code/agno/.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/session_store.py --verify
```

Use PostgreSQL in production. Transcript storage supports PostgresDb, AsyncPostgresDb, SqliteDb, and AsyncSqliteDb. `project_key` defaults to the agent id; set a stable tenant-specific value when sharing a database. Other database adapters retain local-file resume behavior. The adapter does not change `CLAUDE_CONFIG_DIR`; set an ephemeral directory in each container. Workspace files are not persisted by this store.
