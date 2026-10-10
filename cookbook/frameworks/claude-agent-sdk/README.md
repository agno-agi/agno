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

## Retries

`ClaudeAgent` takes `retries`, `delay_between_retries` and `exponential_backoff`, the same settings an Agno `Agent` takes. A failed run is retried with the same run id and resumes the SDK session the failed attempt started, so Claude sees the work already done. Errors that would fail again are not retried: `max_turns` and `max_budget_usd` limits, authentication and billing errors, and invalid requests. Cancelled runs are not retried, and cancelling during the backoff wait ends the run.

Three things to know before turning retries on:

- **Combined budget with the job queue.** The durable queue retries a job up to its `max_attempts`, and this setting retries attempts inside each job, so the SDK can be invoked up to `max_attempts × (retries + 1)` times for one run. Set one of the two unless you want that product. On top of both, Claude Code retries transient API errors on its own before reporting a failure, so one Agno attempt can already be several model requests. An error the agent classifies as permanent (limits, authentication, billing, invalid requests) is marked on the run, and the queue fails the job at once instead of re-driving it.
- **Streaming clients see the failed attempt's output first.** The events of a failed attempt have already been sent when the retry starts. The stream then emits a warning event with `type: "retry"` and the new attempt's events follow. Treat everything before that event as superseded: reset the text you have buffered for the run and start again from the event; keep the tool events, since those tools ran. The event carries `attempt` (the attempt that failed, counting from 1), `attempts` (the total allowed) and `delay`, and a run that was retried stores `metadata["attempts"]`. Everything before that event is superseded: either discard it or label it as a failed attempt. The final `RunCompleted` content and the stored run hold only the last attempt's answer; tool calls from every attempt are kept because they ran.
- **Tools are not exactly-once.** The retry resumes the same SDK session and re-sends the prompt, so Claude sees what the failed attempt did but may run a tool again. A tool that completed before the failure is not undone. The same holds when the durable queue re-drives a job after a worker crash: the job restarts from the beginning and tools that already ran run again. Anything a tool changes outside the workspace (an API call, a message, a payment) must be idempotent, or keyed so a repeat is a no-op, before enabling agent retries or queue `max_attempts` above 1.

`claude_retries.py` makes the failure happen on purpose so the retry can be watched: it cuts the first attempt off with a simulated transient error after Claude has answered, then shows the retry resuming the same SDK session, a run that exhausts its retries, a `max_turns` limit that is not retried, and the default of no retries.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_retries.py
```

## Continue from a step

The `continue_from/` folder has one cookbook per scenario: continue a finished run with a new instruction, fork from a tool checkpoint, replay or rewrite the prompt, continue in the background, and the same flow over the AgentOS API. See `continue_from/README.md`.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/01_continue_finished_run.py
```

`ClaudeAgent.continue_run` / `acontinue_run` take the same `continue_from` and `fork` arguments as `Agent.continue_run`, and AgentOS serves them through `/agents/{id}/runs/{run_id}/continue` and `/checkpoints`. Each tool result is a checkpoint. Continuing forks the Claude SDK transcript at that message, so the model only remembers what happened up to it; `continue_from="last_user"` without `input` re-sends the original prompt. A finished run is never rewritten in place: like native agents, its continuation is a new sibling run with `forked_from_run_id`, whatever `fork` is set to. Later turns in the session continue from the newest branch.

Requires a database with transcript storage, and only runs recorded with it can be continued. Files the agent changed after the checkpoint are not rewound. `regenerate` and HITL `requirements` are not supported.

## Compaction

Claude Code compacts a long conversation into a summary on its own when the context window fills, or when asked with `/compact`. Through `ClaudeAgent` the slash command is an ordinary run input, and a `PreCompact` hook passed in `options_kwargs` sees every compaction. With transcript storage the compaction lands in `agno_transcripts` like any other line: a `compact_boundary` system entry followed by the summary. A later turn on any replica resumes from the database and continues from that summary.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/compaction.py
```

A very short conversation returns "Not enough messages to compact"; the cookbook adds a few turns first.

## Metrics

Every run reports the tokens, cache usage and cost Claude Code returned for the turn on `RunOutput.metrics`, with one entry per model in `metrics.details["model"]` (Claude Code uses a small helper model next to the main one, and subagents may use others). Agno adds wall-clock `duration` and, when streaming, `time_to_first_token`. The `RunCompleted` event carries the same metrics. Completed runs are added to `session_data["session_metrics"]`, which AgentOS reads for the sessions list, the session view and the metrics page. Like the native Anthropic model, `input_tokens` excludes the cached prefix; cached tokens are in `cache_read_tokens` and `cache_write_tokens`.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/metrics.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/metrics_agentos.py --verify
```

`metrics_agentos.py` serves the agent through AgentOS; `--verify` drives two runs over HTTP and prints the run metrics, the session totals, the sessions list token column and the daily aggregation from `/metrics`.

`cache_read_tokens` counts every API call inside the turn. Claude Code's system prompt, tool schemas and project context are a cached prefix of roughly 15k tokens, and a turn with one tool call makes two API calls, so a cache read figure around 30k for such a turn is expected. Cached reads are billed at a tenth of the input price, which is why cost stays low.

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
