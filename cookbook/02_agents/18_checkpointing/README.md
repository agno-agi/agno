# Checkpointing

Three examples covering the run-checkpointing feature: opt-in mid-run persistence
via `checkpoint="steps"` and the unified `/continue` endpoint that advances any
persisted run from its current state.

| Example | What it shows |
|---|---|
| [`01_crash_recovery.py`](./01_crash_recovery.py) | `checkpoint="steps"` writes after each tool batch. If the agent process dies mid-run, the DB has the latest checkpoint and `/continue` resumes from there. |
| [`02_time_travel.py`](./02_time_travel.py) | `/continue` with `from_checkpoint=K` truncates the run's messages to index K, then resumes. Useful for "undo" or exploring earlier states. |
| [`03_forking.py`](./03_forking.py) | `/continue` with `fork=true` clones the run at a checkpoint with a new `run_id`. The original is untouched; the fork becomes a sibling within the same session. |

## When to use `checkpoint="steps"`

The default `checkpoint="runs"` writes to the DB only at terminal states
(`COMPLETED`, `PAUSED`, `CANCELLED`, `ERROR`). If a worker crashes mid-run, the
session row exists but this `run_id` is never recorded — the work is lost.

`checkpoint="steps"` writes after each model turn (post-gather barrier). For a
run with K tool batches and a final no-tool turn, you get K + 1 DB writes (K
mid-run + 1 terminal). The write-amplification is real on the `session.runs`
JSON column in 2.x — opt in deliberately for long research runs and
crash-recoverable workflows, not for chatty agents.

## The unified `/continue`

`/continue` no longer requires a PAUSED run. It dispatches on the body shape:

| Body | Behavior |
|---|---|
| `tools=[...]` (PAUSED + HITL) | Apply tool results, resume |
| empty (resolved admin approval) | Apply resolution, resume |
| empty (INTERRUPTED / ERROR / RUNNING / COMPLETED) | Resume from last persisted state |
| `input="..."` | Append a new user message before resuming |
| `from_checkpoint=K` | Truncate messages to length K, then resume |
| `from_checkpoint=K, fork=true` | Clone with a new run_id, truncate, resume as sibling |

These compose — e.g. `from_checkpoint=14, fork=true, input="try a different angle"`.

## Running the examples

```bash
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/01_crash_recovery.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/02_time_travel.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/03_forking.py
```

Each example uses a local SQLite DB so the persisted state can be inspected with
any SQLite client.
