# Claude Agent SDK

Use `ClaudeAgent` to run Claude Code through Agno and AgentOS. Install `claude-agent-sdk` and configure Claude authentication in your environment.

## Durable transcripts

`session_store.py --verify` starts two independent processes with separate empty `CLAUDE_CONFIG_DIR` directories. The first stores a fact and mirrors the Claude transcript to SQLite. Its Agno run history is removed so the second process must resume the SDK transcript from the database to recall the fact.

```bash
PYTHONPATH=libs/agno .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/session_store.py --verify
```

Use PostgreSQL in production. Transcript storage supports PostgresDb, AsyncPostgresDb, SqliteDb, and AsyncSqliteDb. `project_key` defaults to the agent id; set a stable tenant-specific value when sharing a database. Other database adapters retain local-file resume behavior. The adapter does not change `CLAUDE_CONFIG_DIR`; set an ephemeral directory in each container. Workspace files are not persisted by this store.

### Authentication with an empty config directory

The fresh `CLAUDE_CONFIG_DIR` also hides local login state. Export `ANTHROPIC_API_KEY` before running the example; both child processes inherit it. Our verification used the API key exported by the repository's `.envrc`, without reading or printing credentials. Remove `AGNO_DEBUG` and `AGNO_MONITOR` for clean logs.

If no API key is available, run `claude setup-token` interactively and export its result as `CLAUDE_CODE_OAUTH_TOKEN`. For file-based login, copy only `~/.claude/.credentials.json` into each fresh config directory. Do not copy project transcripts. macOS Keychain login alone does not authenticate a process using an empty custom config directory.

### Transcript write failures

If the SDK exhausts transcript-store retries, the response remains completed and retains its content.
`RunOutput.metadata["warnings"]` contains a `transcript_persistence_failed` warning, also saved in run
history. Streaming callers receive a `CustomEvent` with the same `warning` object. The warning means
another replica may be unable to recover the complete conversation. The adapter does not reexecute
completed model work or tool side effects to repair the mirror.
