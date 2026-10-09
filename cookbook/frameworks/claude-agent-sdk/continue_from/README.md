# Continue a ClaudeAgent run from a step

`ClaudeAgent.continue_run` / `acontinue_run` take the same `continue_from` and `fork` arguments as `Agent.continue_run`, and AgentOS serves them through the same `/continue` and `/checkpoints` endpoints.

## How it works

Every run stores its messages in Agno, and with transcript storage the Claude conversation itself is mirrored into the `agno_transcripts` table. Each tool result in a run is a checkpoint. Continuing from a checkpoint forks the Claude conversation at that message, so the model only remembers what happened up to it, and the continuation runs as a new turn on that branch.

| Call | Effect |
|------|--------|
| `continue_from="end"` (default) with `input` | Append a new instruction after the last message. |
| `continue_from=<message_index>` with `input` | Branch at that checkpoint; the model forgets everything after it. |
| `continue_from="last_user"` without `input` | Re-send the original prompt and produce a fresh answer. |
| `continue_from=0` with `input` | Branch before the prompt, so `input` replaces it. |

A finished run is never rewritten in place. Whatever `fork` is set to, the continuation is a new run in the same session with `forked_from_run_id` and `forked_from_message_index` set, and the source run is kept as is. Later turns in the session continue from the newest branch.

If a later turn cannot resume its SDK session, history recovery follows the active branch's ancestry. Discarded sibling replies are excluded, and the retained source messages appear only once. AgentOS streams and buffers continuation events under the new run's ID, including when a completed run forks automatically; use that ID to resume the branch's stream.

## Cookbooks

Each cookbook seeds a temporary workspace with a small realistic task and asserts on files, tool results and run lineage rather than on the model's wording.

| File | Scenario | What it shows |
|------|----------|---------------|
| `01_continue_finished_run.py` | Write a Python module and run it, then ask for tests for "the function you just wrote". | A continuation remembers the source run; it is a new run with `forked_from_run_id`. |
| `02_fork_from_checkpoint.py` | Three Bash steps over a CSV file: count rows, sum a column, write a summary. Fork after step one. | The branch knows the row count and not the total; checkpoint listing; files are not rewound. |
| `03_replay_user_turn.py` | List markdown files, add a file, replay the prompt; then rewrite the prompt from message 0. | Replay re-runs tools against the current workspace; `continue_from=0` replaces the prompt. |
| `04_background_continue.py` | Write a script, then run it in a background continuation with `stream=True`. | Live tool and content events from a background run, the final `RunOutput`, and the stored result. |
| `05_agentos_api.py` | The CSV scenario over HTTP. `--verify` runs it end to end. | `/checkpoints`, `/continue` with `fork=true`, a streamed follow-up, and the session's run lineage. |

A script that consumes a background stream and exits at once can log "Failed to complete event stream": the final output reaches the client before the run finishes its event-stream bookkeeping, and closing the loop cancels that step. `await_background_runs()` from `agno.run.background` waits for it; a server keeps its loop alive and does not need it.

The SDK's default system prompt does not tell the model its working directory, so the cookbooks that create files set `system_prompt` to name it. Bash already runs in `cwd`.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/01_continue_finished_run.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/02_fork_from_checkpoint.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/03_replay_user_turn.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/04_background_continue.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/05_agentos_api.py --verify
```

## Limits

- Requires a database with transcript storage (SqliteDb, AsyncSqliteDb, PostgresDb, AsyncPostgresDb). Only runs recorded with it can be continued.
- Files the agent changed after a checkpoint are not rewound; only the conversation is.
- Cancelled runs cannot be continued.
- When Claude issues several tool calls in parallel, the batch is a single checkpoint and a branch keeps all of its results.
- `regenerate` and HITL `requirements` are not supported for ClaudeAgent.
