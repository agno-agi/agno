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

## Metrics

Every run reports the token usage for the whole turn on `RunOutput.metrics` (input, cached input, output, reasoning and total), plus wall-clock `duration` measured by Agno and `time_to_first_token` when streaming. A turn with tool calls makes several model requests; Codex reports usage after each one, and the adapter sums them by taking the growth of the thread total over the turn, so a two-tool turn reports all three requests rather than only the last. Like the OpenAI API, `input_tokens` includes the cached prefix. Codex reports no cost. Completed runs are added to `session_data["session_metrics"]`, which AgentOS reads for the sessions list, the session view and the metrics page.

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
