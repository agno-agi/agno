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
- `codex_tools.py` — shell commands in a read-only sandbox, surfaced as Agno tool calls
- `codex_session.py` — multi-turn session; the Codex thread is resumed across turns via Agno's DB
- `codex_mcp_tools.py` — connect Codex to an MCP server through `config` overrides
- `codex_structured_output.py` — constrain the final answer with a JSON Schema
- `codex_retries.py` — retry failed runs with exponential backoff. The cookbook injects a transient failure so the retry can be watched resuming the failed attempt's thread, then shows exhaustion and the default of no retries. Limits and permanent errors are not retried
- `codex_agentos.py` — serve Codex through AgentOS
- `codex_session_agentos.py` — same with SQLite-backed sessions

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

- **Combined budget with the job queue.** The durable queue retries a job up to its `max_attempts`, and this setting retries attempts inside each job, so Codex can be invoked up to `max_attempts × (retries + 1)` times for one run. Set one of the two unless you want that product. An error the agent classifies as permanent is marked on the run, and the queue fails the job at once instead of re-driving it.
- **Streaming clients see the failed attempt's output first.** The stream emits a warning event with `type: "retry"` between the failed attempt's events and the new attempt's. Treat everything before that event as superseded. The final `RunCompleted` content and the stored run hold only the last attempt's answer; tool calls from every attempt are kept because they ran.
- **Tools are not exactly-once.** The retry resumes the same thread and re-sends the prompt, so Codex sees what the failed attempt did but may run a command again. A command that completed before the failure is not undone. Make tools idempotent or keep `retries=0` where a repeated side effect would be harmful.

## Sandbox and approvals

| Setting | Values | Notes |
|---|---|---|
| `sandbox` | `read-only`, `workspace-write`, `full-access` | Filesystem access for commands and edits |
| `approval_mode` | `auto_review`, `deny_all` | How escalated permission requests are handled. There is no interactive prompt, so `deny_all` is the safe choice for unattended servers |

Test results are tracked in `TEST_LOG.md`.

## Background runs and cancellation

`background_cancel.py` serves the agent through AgentOS. Submit runs with `background=true`, poll the run endpoint, or use `stream=true` for indexed SSE. Runs continue after disconnects; the resume endpoint reads the configured event stream. Cancel through the run cancellation endpoint.

Run `background_cancel.py --verify` to start a real streamed turn, cancel after its first content event, and verify CANCELLED in the database. Multi-replica resume and cancellation require shared event-stream and cancellation-manager backends. Stored-event replay after the event-stream TTL is a follow-up.

The Codex example uses `approval_mode="deny_all"`. The SDK default accepts escalation requests, which is unsuitable for unattended servers.
