# Claude Agent SDK

Use `ClaudeAgent` to run Claude Code through Agno and AgentOS. Install `claude-agent-sdk` and configure Claude authentication in your environment.

## Durable transcripts

Claude Code keeps each conversation as a JSONL transcript on the local disk of the machine that ran it. When `ClaudeAgent` has a database that supports transcript storage, every transcript line is also mirrored into the `agno_transcripts` table, and a later turn on any machine resumes the conversation from the database instead of the local file.

`transcript_store.py` runs the whole flow and prints the table after each step. Replica A runs a turn and stores a fact. Replica B is a second agent instance with a different working directory, so replica A's local transcript is invisible to it. It resumes from the database, answers from the stored conversation, and appends its own lines to the same transcript.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/transcript_store.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/transcript_store.py --postgres
```

The `--postgres` flag uses the container from `cookbook/scripts/run_pgvector.sh`. A normal `claude login` or `ANTHROPIC_API_KEY` is enough: for a store-backed resume the SDK writes the transcript into a temporary config directory and copies the caller's credentials into it, including macOS Keychain logins.

Use PostgreSQL in production. Transcript storage supports PostgresDb, AsyncPostgresDb, SqliteDb, and AsyncSqliteDb. `project_key` defaults to the agent id; set a stable tenant-specific value when sharing a database. Other database adapters retain local-file resume behavior. Workspace files are not persisted by this store.

The `agno_transcripts` table is created on first use. A development database that ran an earlier build of this feature has an older table shape and raises a schema mismatch; drop the table and it is recreated.

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

### When transcripts stay on local disk

A database without transcript storage logs a warning once and the agent continues with the SDK's
local-disk transcripts, so resume works on the machine that ran the session. Transcript storage is also
skipped, with a warning, when `enable_file_checkpointing` is set in `options_kwargs`, because the SDK
does not allow the two together. A `session_store` supplied in `options_kwargs` is used as is.
