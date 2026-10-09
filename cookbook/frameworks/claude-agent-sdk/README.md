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

## Continue from a step

`continue_from.py` runs a two-step Bash task, lists its checkpoints, then continues from the first tool result and replays the whole turn.

```bash
PYTHONPATH=libs/agno .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from.py
```

`ClaudeAgent.continue_run` / `acontinue_run` take the same `continue_from` and `fork` arguments as `Agent.continue_run`, and AgentOS serves them through `/agents/{id}/runs/{run_id}/continue` and `/checkpoints`. Each tool result is a checkpoint. Continuing forks the Claude SDK transcript at that message, so the model only remembers what happened up to it; `continue_from="last_user"` without `input` re-sends the original prompt. `fork=True` adds a sibling run with `forked_from_run_id`; otherwise the source run is replaced in place. Later turns in the session continue from the replayed branch.

Requires a database with transcript storage, and only runs recorded with it can be continued. Files the agent changed after the checkpoint are not rewound. `regenerate` and HITL `requirements` are not supported.

## Background runs and cancellation

`background_cancel.py` serves the agent through AgentOS. Submit runs with `background=true`, poll the run endpoint, or use `stream=true` for indexed SSE. Runs continue after disconnects; the resume endpoint reads the configured event stream. Cancel through the run cancellation endpoint.

Run `background_cancel.py --verify` to start a real streamed turn, cancel after its first content event, and verify CANCELLED in the database. Multi-replica resume and cancellation require shared event-stream and cancellation-manager backends. Stored-event replay after the event-stream TTL is a follow-up.


### Transcript write failures

If the SDK exhausts transcript-store retries, the response remains completed and retains its content.
`RunOutput.metadata["warnings"]` contains a `transcript_persistence_failed` warning, also saved in run
history. Streaming callers receive a `CustomEvent` with the same `warning` object. The warning means
another replica may be unable to recover the complete conversation. The adapter does not reexecute
completed model work or tool side effects to repair the mirror.
