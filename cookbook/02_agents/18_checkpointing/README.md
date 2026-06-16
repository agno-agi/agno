# Checkpointing & /continue

Examples covering mid-run persistence (`checkpoint="tool-batch"`) and the unified
`/continue` endpoint that advances any persisted run from its current state.

| Example | What it shows |
|---|---|
| [`01_crash_recovery.py`](./01_crash_recovery.py) | `checkpoint="tool-batch"` writes after each tool batch. If the agent process dies mid-run, the DB has the latest checkpoint and `/continue` resumes from there. |
| [`02_time_travel.py`](./02_time_travel.py) | `/continue` with `continue_from="end"`, `"last_user"`, and a raw integer index. COMPLETED runs auto-fork, so the source is preserved. |
| [`03_forking.py`](./03_forking.py) | `/continue` with `continue_from="last_user", fork=True` and the numeric form `continue_from=K, fork=True` — non-destructive siblings in the same session. |
| [`04_regenerate.py`](./04_regenerate.py) | `/continue` with `regenerate=True` to redo the last response. Drops only the trailing assistant reply, **keeping intermediate tool exchanges** so tools aren't re-invoked. Pair with `additional_instructions` to steer, `replace_original=True` to hide the old one. |
| [`05_branch_session.py`](./05_branch_session.py) | `agent.branch_session()` deep-copies every run into a **new session**. Different from `fork`, which makes a sibling run in the *same* session. |
| [`06_tool_error_persistence.py`](./06_tool_error_persistence.py) | When a tool raises mid-run, in-flight messages are flushed onto the ERROR row so the failed conversation isn't lost. |
| [`07_checkpoint_endpoints.py`](./07_checkpoint_endpoints.py) | Calls the two new GET endpoints — `/checkpoints` (timeline) and `/checkpoints/{message_index}` (snapshot) — via an in-process `TestClient`, prints raw payloads, and feeds the returned `message_index` back into `/continue`. |

## When to use `checkpoint="tool-batch"`

The default `checkpoint="runs"` writes to the DB only at terminal states
(`COMPLETED`, `PAUSED`, `CANCELLED`, `ERROR`). If a worker crashes mid-run, the
session row exists but this `run_id` is never recorded — the work is lost.

`checkpoint="tool-batch"` writes after each model turn (post-gather barrier). For a
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
| empty + RUNNING / ERROR | **Resume in place** — the original loop never completed, so we continue the same `run_id` |
| empty + COMPLETED | **Auto-fork** — a new `run_id` is created, source is preserved. Prevents two model loops from sharing one row. |
| `input="..."` | Append a new user message before resuming (auto-forks if source is COMPLETED) |
| `continue_from="end"` | Resume from the current end of the transcript |
| `continue_from="last_user"` | Resume just after the last user message — drops the whole post-user tail including intermediate tool exchanges (tools will be re-invoked) |
| `continue_from=K` | Low-level numeric message index fallback |
| `regenerate=True` | **Always forks.** Drops only the trailing no-tool-call assistant message and keeps intermediate tool exchanges (tools NOT re-invoked) |
| `regenerate=True, additional_instructions="..."` | Same, with steering text appended |
| `regenerate=True, replace_original=True` | Same + mark source `REGENERATED` so it's hidden from future history |

**The 1-run-1-loop invariant.** Whenever a model loop has already finished (status COMPLETED), `/continue` produces a new `run_id`. This is structural — there's no way to mix two model loops' metrics into one row. Only mid-flight resumes (RUNNING / ERROR / PAUSED — the loop never actually finished) stay on the same `run_id`.

These compose:

```python
await agent.acontinue_run(
    run_id=...,
    regenerate=True,
    replace_original=True,
    additional_instructions="be more concise",
)
```

## When to use which "redo last response"

| You want | Use |
|---|---|
| "Redo the last response" (drop assistant reply, fresh run_id) | `regenerate=True` |
| Same, and hide the original from future history | `regenerate=True, replace_original=True` |
| Same, with a steering message | `regenerate=True, additional_instructions="..."` |
| Drop the last *3* messages, not just the assistant reply | `continue_from=K` |
| Drop messages *and* keep the old run | `continue_from=K, fork=True` |

The sugar (`regenerate=*`) is just internal math over the raw params
(`continue_from`, `fork`, `input`).

## `regenerate=True` vs `continue_from="last_user"`

Both rewind to the same "after the user spoke" general area, but they cut
differently when tools are involved:

| Form | What it keeps | What it drops | Tools re-invoked? |
|---|---|---|---|
| `regenerate=True` | Everything up to and including the last tool exchange | Only the trailing no-tool-call assistant turn | No |
| `continue_from="last_user"` | Everything up to and including the last user message | Whole post-user tail (assistant tool_calls, tool results, final reply) | Yes |

Use `regenerate=True` for "redo the final summary, same tool results" (cheap,
deterministic input). Use `continue_from="last_user"` for "rewind to where the
user spoke and try the whole turn fresh" (costs tool calls but explores a
different reasoning path).

## Checkpoint endpoints for UI

These endpoints expose checkpoint boundaries without adding a separate
checkpoint table:

| Endpoint | Use |
|---|---|
| `GET /agents/{agent_id}/runs/{run_id}/checkpoints?session_id=...` | List message boundaries the UI can display |
| `GET /agents/{agent_id}/runs/{run_id}/checkpoints/{message_index}?session_id=...` | Get a derived run snapshot truncated at that boundary |

The returned `message_index` can be passed back as `continue_from=K`.

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
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/06_tool_error_persistence.py
.venvs/demo/bin/python cookbook/02_agents/18_checkpointing/07_checkpoint_endpoints.py
```

Each example uses a local SQLite DB so the persisted state can be inspected
with any SQLite client.
