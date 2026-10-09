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

## Cookbooks

| File | What it shows |
|------|---------------|
| `01_continue_finished_run.py` | Continue a completed run with a new instruction; the model remembers the source run. |
| `02_fork_from_checkpoint.py` | List checkpoints and fork from a tool step; the branch carries only the earlier tool results. |
| `03_replay_user_turn.py` | Replay the original prompt, or rewrite it from message 0. |
| `04_background_continue.py` | Submit a continuation with `background=True` and poll the database for the result. |
| `05_agentos_api.py` | Serve the agent and use `/checkpoints` and `/continue` over HTTP (`--verify` runs the flow end to end). |

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
