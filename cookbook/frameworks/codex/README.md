# Codex

Examples for running [OpenAI Codex](https://developers.openai.com/codex) as an Agno agent.

`CodexAgent` wraps the official [Codex Python SDK](https://github.com/openai/codex/tree/main/sdk/python)
(`pip install openai-codex`). The SDK ships the Codex CLI, which runs locally as an
app-server subprocess and executes the full agent loop: shell commands, file edits,
web search and MCP tool calls. Agno adds sessions, streaming, the AgentOS API and the UI.

## Setup

```bash
pip install openai-codex

# Authenticate once. Either sign in with ChatGPT through the Codex CLI...
codex login
# ...or use an API key
export CODEX_API_KEY=sk-...   # OPENAI_API_KEY also works
```

If the `codex` CLI is not on your PATH you can also authenticate from Python:

```python
from agno.agents.codex import CodexAgent

CodexAgent(name="Codex").login_api_key("sk-...")
```

## Files

- `codex_basic.py` — minimal standalone run with `.print_response()`
- `codex_tools.py` — shell commands in a read-only sandbox, surfaced as Agno tool calls. A command that exits non-zero, a declined command, or an MCP tool that fails is stored with `tool_call_error=True` and its output or error message as the result
- `codex_session.py` — multi-turn session; the Codex thread is resumed across turns via Agno's DB
- `codex_mcp_tools.py` — connect Codex to an MCP server through `config` overrides
- `codex_structured_output.py` — constrain the final answer with a JSON Schema
- `codex_retries.py` — retry failed runs with exponential backoff. The cookbook injects a transient failure so the retry can be watched resuming the failed attempt's thread, then shows exhaustion and the default of no retries. Limits and permanent errors are not retried
- `codex_agentos.py` — serve Codex through AgentOS
- `codex_session_agentos.py` — same with SQLite-backed sessions
- `codex_compaction.py` — compact the Codex thread behind a session with `CodexAgent.acompact` (a full-access agent with instructions and an approval mode), continue from the summary, then the guards: compaction refuses while a background run on the session is in flight, and a stored thread id whose rollout is gone is forgotten

- `codex_metrics.py` — token usage per run on `RunOutput.metrics` and session totals for AgentOS
- `codex_metrics_agentos.py` — the same through the AgentOS API (`--verify` prints run, session, sessions list and `/metrics`)

## How sessions work

Each Agno `session_id` maps to one Codex thread. The thread id is stored on the
Agno session (`session_data["codex_thread_id"]`) when a `db` is configured, so
the mapping survives restarts. Without a `db` the mapping is kept in memory for
the lifetime of the agent object.

If a thread cannot be resumed (for example `ephemeral=True`, or the Codex
session files were removed), the adapter starts a fresh thread and prepends the
persisted chat history to the prompt so context is not lost.

## Retries

`CodexAgent` takes `retries`, `delay_between_retries` and `exponential_backoff`, the same settings an Agno `Agent` takes. A failed attempt is retried with the same run id and resumes the Codex thread the failed attempt started. Errors that would fail again are not retried: session budget and usage limits, context window overflows, authentication, bad requests and policy blocks. Cancelled runs are not retried.

- **Combined budget with the job queue.** The durable queue retries a job up to its `max_attempts`, and this setting retries attempts inside each job, so Codex can be invoked up to `max_attempts × (retries + 1)` times for one run. Set one of the two unless you want that product. On top of both, the Codex CLI retries transient API errors on its own before reporting a failure, so one Agno attempt can already be several model requests. An error the agent classifies as permanent is marked on the run, and the queue fails the job at once instead of re-driving it.
- **Streaming clients see the failed attempt's output first.** The stream emits a warning event with `type: "retry"` between the failed attempt's events and the new attempt's. Treat everything before that event as superseded: reset the text you have buffered for the run and start again from the event; keep the tool events, since those tools ran. The event carries `attempt` (the attempt that failed, counting from 1), `attempts` (the total allowed) and `delay`, and a run that was retried stores `metadata["attempts"]`. Everything before that event is superseded. The final `RunCompleted` content and the stored run hold only the last attempt's answer; tool calls from every attempt are kept because they ran.
- **Tools are not exactly-once.** The retry resumes the same thread and re-sends the prompt, so Codex sees what the failed attempt did but may run a command again. A command that completed before the failure is not undone. The same holds when the durable queue re-drives a job after a worker crash: the job restarts from the beginning and tools that already ran run again. Anything a tool changes outside the workspace (an API call, a message, a payment) must be idempotent, or keyed so a repeat is a no-op, before enabling agent retries or queue `max_attempts` above 1.

## Metrics

Every run reports the token usage for the whole turn on `RunOutput.metrics` (input, cached input, output, reasoning and total), plus wall-clock `duration` measured by Agno and `time_to_first_token` when streaming. A turn with tool calls makes several model requests; Codex reports usage after each one, and the adapter sums them by taking the growth of the thread total over the turn, so a two-tool turn reports all three requests rather than only the last. Like the OpenAI API, `input_tokens` includes the cached prefix. Codex reports no cost. Completed runs are added to `session_data["session_metrics"]`, which AgentOS reads for the sessions list, the session view and the metrics page.

## Sandbox and approvals

| Setting | Values | Notes |
|---|---|---|
| `sandbox` | `read-only`, `workspace-write`, `full-access` | Filesystem access for commands and edits |
| `approval_mode` | `auto_review`, `deny_all` | How escalated permission requests are handled. There is no interactive prompt, so `deny_all` is the safe choice for unattended servers |

Test results are tracked in `TEST_LOG.md`.

## One turn per session

Codex keeps one conversation per Agno session on its side (the thread), and two turns writing to it at once corrupt it. A session therefore takes one turn at a time. A second turn started while one is in flight is refused before anything runs, with `SessionBusyError` (HTTP 409 from AgentOS, a `RunError` event with `error_type: session_busy` on a stream) naming the run in flight; no run is recorded for the refused turn. The check covers the turns this process is running and, when a database is configured, the session's pending and running run rows, so a turn accepted on another replica counts too. The Codex app-server has the same rule for its threads: a turn that slips past the check on another replica is refused by the app-server ("already has an active writer"), which the adapter reports as the same `SessionBusyError`; with `retries` set, that turn waits out the backoff and resumes the thread once it is free.

A run row left pending or running by a crash keeps its session busy until that run is cancelled. The durable queue sweeps crashed queued runs on its own; cancel an orphaned background run through the run cancellation endpoint. A queued turn on a busy session is re-driven after the queue's retry delay when `max_attempts` allows it, which serializes it behind the turn in flight.

## Background runs and cancellation

`background_cancel.py` serves the agent through AgentOS. Submit runs with `background=true`, poll the run endpoint, or use `stream=true` for indexed SSE. Runs continue after disconnects; the resume endpoint reads the configured event stream. Cancel through the run cancellation endpoint. A run submitted with `stream=false` has no event stream to attach to later: nothing is published while it runs and no events are stored with it, so the resume endpoint answers with its status and zero events. Choose `stream=true` at submission when live or replayed events are needed, and poll the run endpoint otherwise.

Run `background_cancel.py --verify` to start a real streamed turn, cancel after its first content event, and verify CANCELLED in the database. Multi-replica resume and cancellation require shared event-stream and cancellation-manager backends. Stored-event replay after the event-stream TTL is a follow-up.

The Codex example uses `approval_mode="deny_all"`. The SDK default accepts escalation requests, which is unsuitable for unattended servers.
