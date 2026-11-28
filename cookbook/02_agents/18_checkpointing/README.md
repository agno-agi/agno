# Checkpointing & Crash Recovery

With `checkpoint="tool-batch"`, an agent saves a fresh foreground run before
the first model call and again after each batch of tool results. The final
write updates the same run. A run with K tool batches has K + 2 writes.
If the process exits before any tools return, the stored run already contains
the user's input and the messages needed for an explicit continuation.

The three `/continue` capabilities that operate on a persisted run live in
sibling folders:

- [`../19_regenerate/`](../19_regenerate/) — redo the last response
- [`../20_time_travel/`](../20_time_travel/) — rewind to an earlier point (`continue_from`, `fork`)
- [`../21_fork_session/`](../21_fork_session/) — copy a whole session

## Examples

| Example | What it shows |
|---|---|
| [`01_crash_recovery.py`](./01_crash_recovery.py) | Cancel an in-flight run to simulate a crash, then prove the DB has the last checkpoint (status `RUNNING`) and `/continue` resumes it in place. |
| [`02_tool_error_persistence.py`](./02_tool_error_persistence.py) | A tool exception is caught and recorded; a model-call failure escapes the loop but the in-flight conversation is flushed onto the `ERROR` row so it survives, and `/continue` retries it. |
| [`03_checkpoint_endpoints.py`](./03_checkpoint_endpoints.py) | The two GET endpoints — `/checkpoints` (timeline) and `/checkpoints/{message_index}` (snapshot) — and feeding a returned `message_index` back into `/continue`. |

## When to use `checkpoint="tool-batch"`

The default `checkpoint="runs"` writes only at terminal states (`COMPLETED`,
`PAUSED`, `CANCELLED`, `ERROR`). If a worker crashes mid-run, the session row
exists but this `run_id` was never recorded — the work is lost.

`checkpoint="tool-batch"` trades extra writes for recoverability. It's real
write-amplification on the `session.runs` JSON column in 2.x — opt in
deliberately for long research runs and crash-recoverable workflows, not for
chatty agents.

`checkpoint="tools"` (per-tool writes) is reserved for 3.0 and raises
`NotImplementedError` today.

## Running

```bash
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/01_crash_recovery.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/02_tool_error_persistence.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/03_checkpoint_endpoints.py
```

Each example uses a local SQLite DB so the persisted state can be inspected
with any SQLite client.
