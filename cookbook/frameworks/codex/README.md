# Codex

Start with the [Codex harness walkthrough](../../harnesses/codex/README.md) for
the refreshed basics, native SDK comparison, tools and AgentOS examples.
Advanced examples below retain their paths during this migration. Historical
test logs refer to original filenames and are not new verification evidence.

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

- [`basic.py`](../../harnesses/codex/basic.py) — standalone run with checked terminal status
- [`tools.py`](../../harnesses/codex/tools.py) — read the shipping fixture and inspect streamed tools
- `codex_session.py` — multi-turn session; the Codex thread is resumed across turns via Agno's DB
- `codex_mcp_tools.py` — connect Codex to an MCP server through `config` overrides
- `codex_structured_output.py` — constrain the final answer with a JSON Schema
- [`agent_os.py`](../../harnesses/codex/agent_os.py) — serve the shipping reviewer through AgentOS
- `codex_session_agentos.py` — same with SQLite-backed sessions

## How sessions work

Each Agno `session_id` maps to one Codex thread. The thread id is stored on the
Agno session (`session_data["codex_thread_id"]`) when a `db` is configured, so
the mapping survives restarts. Without a `db` the mapping is kept in memory for
the lifetime of the agent object.

If a thread cannot be resumed (for example `ephemeral=True`, or the Codex
session files were removed), the adapter starts a fresh thread and prepends the
persisted chat history to the prompt so context is not lost.

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
