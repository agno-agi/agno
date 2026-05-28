# Checkpointing & /continue

Five examples covering mid-run persistence (`checkpoint="steps"`) and the
unified `/continue` endpoint that advances any persisted run from its current
state.

| Example | What it shows |
|---|---|
| [`01_crash_recovery.py`](./01_crash_recovery.py) | `checkpoint="steps"` writes after each tool batch. If the agent process dies mid-run, the DB has the latest checkpoint and `/continue` resumes from there. |
| [`02_time_travel.py`](./02_time_travel.py) | `/continue` with `from_checkpoint=K` truncates the run's messages to index K, then resumes. **Destructive** — the original run is overwritten in place. |
| [`03_forking.py`](./03_forking.py) | `/continue` with `from_checkpoint=K, fork=True` clones the run at K with a new `run_id`. **Non-destructive** sibling run within the same session. |
| [`04_regenerate.py`](./04_regenerate.py) | `/continue` with `regenerate=True` — sugar that auto-picks `from_checkpoint` to redo the last response. Pair with `additional_instructions` to steer, `preserve_original=True` to keep the old one. |
| [`05_branch_session.py`](./05_branch_session.py) | `agent.branch_session()` deep-copies every run into a **new session**. Different from `fork`, which makes a sibling run in the *same* session. |

## When to use `checkpoint="steps"`

The default `checkpoint="runs"` writes to the DB only at terminal states
(`COMPLETED`, `PAUSED`, `CANCELLED`, `ERROR`). If a worker crashes mid-run, the
session row exists but this `run_id` is never recorded — the work is lost.

`checkpoint="steps"` writes after each model turn (post-gather barrier). For a
run with K tool batches and a final no-tool turn, you get K + 1 DB writes (K
mid-run + 1 terminal). Real write-amplification on the `session.runs` JSON
column in 2.x — opt in deliberately for long research runs and
crash-recoverable workflows, not for chatty agents.

## The unified `/continue`

`/continue` no longer requires a PAUSED run. It dispatches on the body shape:

| Body | Behavior |
|---|---|
| `tools=[...]` (PAUSED + HITL) | Apply tool results, resume |
| empty + resolved admin approval | Apply resolution, resume |
| empty (RUNNING / ERROR / COMPLETED) | Resume from last persisted state |
| `input="..."` | Append a new user message before resuming |
| `from_checkpoint=K` | Truncate messages to length K, then resume (**destructive**) |
| `from_checkpoint=K, fork=True` | Clone with a new `run_id`, truncate, resume as sibling |
| `regenerate=True` | Sugar: drop the last assistant turn and replay |
| `regenerate=True, additional_instructions="..."` | Replay with steering text appended |
| `regenerate=True, preserve_original=True` | Non-destructive replay (creates a fork, marks the old run `REGENERATED`) |

The first three resume; the rest rewrite. They compose:

```python
await agent.acontinue_run(
    run_id=...,
    regenerate=True,
    preserve_original=True,
    additional_instructions="be more concise",
)
```

## When to use which "redo last response"

There are three ways to express "redo the last response of this run." Pick by
how much control you need:

| You want | Use |
|---|---|
| "Redo the last response" (drop the assistant reply, replay) | `regenerate=True` |
| Same, but keep the old one too | `regenerate=True, preserve_original=True` |
| Same, but with a steering message | `regenerate=True, additional_instructions="..."` |
| Drop the last *3* messages, not just the assistant reply | `from_checkpoint=K` (raw) |
| Drop messages *and* keep the old run | `from_checkpoint=K, fork=True` |

The sugar (`regenerate=*`) is just internal math over the raw params
(`from_checkpoint`, `fork`, `input`). Both are exposed.

## Fork vs branch_session

| | `fork=True` | `branch_session()` |
|---|---|---|
| Granularity | **Run** | **Session** |
| Result | New sibling run, same session | New session with copies of every run |
| Endpoint | `POST /runs/{run_id}/continue` | `POST /sessions/{session_id}/branch` |
| Lineage field | `run.forked_from_run_id` | `run.branched_from` (session_id) |

Use fork to explore alternatives from one mid-run state. Use branch_session
when you want a whole new conversation thread that starts from the current
state.

## Running the examples

```bash
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/01_crash_recovery.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/02_time_travel.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/03_forking.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/04_regenerate.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/05_branch_session.py
```

Each example uses a local SQLite DB so the persisted state can be inspected
with any SQLite client.
