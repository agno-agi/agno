# Run Lifecycle

These five examples cover the lifecycle APIs around an AgentOS agent run:
background submission and polling, cancellation, resumable SSE, persisted
checkpoints, and background hooks.

## Setup

From the repository root, use the cookbook environment:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=your-key
```

Each server example listens on port 7777. Start only one at a time.

## Files

| File | What it teaches |
|---|---|
| `background_run.py` | Submit a database-backed run for HTTP 202/PENDING and poll its nested run route. |
| `cancel_run.py` | Cancel an accepted background run and observe its persisted terminal status. |
| `sse_reconnect.py` | Resume both a new background SSE run and a background continuation with raw `httpx`. |
| `checkpoints.py` | List `tool-batch` checkpoints and continue from a selected `message_index`. |
| `hooks_in_background.py` | Choose AgentOS-wide background hooks or mix blocking and per-hook background work. |

## Examples

### `background_run.py`

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/background_run.py
```

Terminal 2:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/background_run.py --demo
```

The client explicitly sends `background=true`, `stream=false`, and a
`session_id`. AgentOS returns HTTP 202 with `PENDING`; the client then polls
`GET /agents/{agent_id}/runs/{run_id}?session_id=...` until completion.

A database on the served agent is required because the detached task and poll
request use persisted run state. This mode does not support remote agents.

### `cancel_run.py`

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/cancel_run.py
```

Terminal 2:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/cancel_run.py --demo
```

The client starts the same HTTP 202/PENDING background flow, posts to
`/agents/{agent_id}/runs/{run_id}/cancel` with the returned `session_id`, and
polls the nested run route until it observes `CANCELLED`.

### `sse_reconnect.py`

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/sse_reconnect.py
```

Terminal 2 can exercise either reconnection path:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/sse_reconnect.py --demo run
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/sse_reconnect.py --demo continue
```

Both clients track the latest `event_index`, disconnect from a
`background=true`, `stream=true` response, and reconnect with
`POST /agents/{agent_id}/runs/{run_id}/resume`. The second client first creates
a confirmation pause and calls the nested `/continue` route in background mode.

`AgentOSClient` does not currently expose a resume method, so this example
intentionally uses raw `httpx` for both the original SSE response and the
resume request.

### `checkpoints.py`

Terminal 1:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/checkpoints.py
```

Terminal 2:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/checkpoints.py --demo
```

The agent uses `checkpoint="tool-batch"`. The client calls the nested
`/checkpoints` route with `session_id`, selects an interior boundary by its
`message_index`, and posts that value as `continue_from` to `/continue`.
`checkpoint_id` is a display ordinal; it is not the continuation coordinate.

### `hooks_in_background.py`

Run the AgentOS-wide mode:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/hooks_in_background.py --mode global
```

Then POST a run for `global-hooks-agent`. In this mode,
`AgentOS(run_hooks_in_background=True)` schedules every non-guardrail pre- and
post-hook as a FastAPI background task. Guardrails remain synchronous so they
can still block unsafe input or output.

```bash
curl -X POST http://localhost:7777/agents/global-hooks-agent/runs \
  -F 'message=Explain background hooks in one sentence.' \
  -F 'stream=false' \
  -F 'session_id=global-hooks-demo'
```

Run the fine-grained mode:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/04_run_lifecycle/hooks_in_background.py --mode mixed
```

Then POST a run for `mixed-hooks-agent`. This mode leaves
`run_hooks_in_background` at its default so the plain hook and first
`AgentAsJudgeEval` block. The `@hook(run_in_background=True)` notification and
the second `AgentAsJudgeEval(run_in_background=True)` are scheduled after the
response.

```bash
curl -X POST http://localhost:7777/agents/mixed-hooks-agent/runs \
  -F 'message=Explain mixed hook execution in one sentence.' \
  -F 'stream=false' \
  -F 'session_id=mixed-hooks-demo'
```

The same global switch and per-hook controls apply to AgentOS teams and
workflows.
