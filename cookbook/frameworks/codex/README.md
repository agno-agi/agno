# Codex: SDK to AgentOS

Start with the [shared setup](../README.md#start-here), then install the tested
SDK version in that environment:

```bash
uv pip install 'openai-codex==0.162.1'
```

Authenticate through your existing Codex CLI login (`codex login`), or use
the SDK's API-key login once. If the CLI is not on your PATH, export
`OPENAI_API_KEY` in your shell and run:

```bash
python - <<'PY'
import os
from openai_codex import Codex

with Codex() as codex:
    codex.login_api_key(os.environ["OPENAI_API_KEY"])
PY
```

This stores authentication using the SDK's login mechanism. Do not put
credentials in the example files. The examples default to `gpt-5.6-luna`;
`CODEX_MODEL` overrides it.
The Python SDK supplies a pinned Codex app-server runtime.

## 1. Run the smallest example

```bash
python cookbook/frameworks/codex/codex_basic.py
```

Inspect the answer and Agno run ID. An order of exactly 100 dollars qualifies
for free shipping. This prompt contains the policy, so no file read is needed.
The script uses `print_response()`, which displays the terminal status and raises
on failed or cancelled runs, so errors exit nonzero. The method returns the final
`RunOutput`; its async equivalent is `aprint_response()`. See the shared
[3.2 migration notes](../README.md#adapter-api-changes-for-32).

## 2. Compare with the native SDK

```bash
python cookbook/frameworks/codex/codex_native_sdk.py
```

The prompt, model and corresponding execution settings match `codex_basic.py`.
The native example creates an `AsyncCodex` client, a thread and a turn.
Agno manages those calls and returns a `RunOutput`. Codex still executes the
agent loop; its native thread ID is distinct from an Agno run/session ID.

The comparison is about API shape, not identical prose or latency. These
one-shot scripts do not configure an Agno database or establish durable resume.

Official reference: [Codex Python SDK](https://learn.chatgpt.com/docs/codex-sdk#python-library).

## 3. Watch actual tools

```bash
python cookbook/frameworks/codex/codex_tools.py
```

This time the policy is not supplied in the prompt: the harness must read
`shipping.py` and `orders.json`. Observe text deltas and tool start/end events,
including the returned file contents. Expect fees of 8, 0 and 0 dollars.
The script checks that at least one tool succeeded; the live test also checks
fixture contents in the output. Inspect the final explanation yourself.

The thread uses `sandbox="read-only"` and `approval_mode="deny_all"`.
Shell reads are translated into Agno tool events. Codex can inherit other local
configuration; this is a local integration exercise, not a tenant-isolation
demonstration. We do not use full-access mode or auto-approve escalation.

## 4. Serve the same review through AgentOS

```bash
python cookbook/frameworks/codex/codex_agentos.py
```

In another terminal:

```bash
curl -fsS http://127.0.0.1:7777/health
curl -fsS http://127.0.0.1:7777/agents
curl -fsS http://127.0.0.1:7777/agents/codex-reviewer/runs \
  -F 'message=Read shipping.py and orders.json. Explain the fee for each order. Do not modify files.' \
  -F 'session_id=codex-shipping-review' -F 'stream=false'
```

Repeat with `stream=true` and `curl --no-buffer` to see SSE. Run one provider
server at a time, or set `PORT=7778` for the second server.

Copy the returned `run_id` and read the stored result:

```bash
curl -fsS 'http://127.0.0.1:7777/agents/codex-reviewer/runs/RUN_ID?session_id=codex-shipping-review'
```

Agno stores product-facing run/tool data in `tmp/harnesses/codex/runs.db`.
The Agno session stores `codex_thread_id`; Codex's authoritative rollout
files remain in its local Codex home, not this SQLite database. A stored thread
ID alone is insufficient on a different machine. See the
[existing session examples](#how-sessions-work).

The local server has no authentication. Use PostgreSQL and explicit
authorization for production. Background jobs, disconnects and recovery are
follow-up exercises, not guarantees demonstrated here.

## Validate and continue

Use [TEST_PROMPT.md](../TEST_PROMPT.md) for reproducible live tests and
[TEST_LOG.md](TEST_LOG.md) for observations. Continue with the session, MCP and background examples below.


## More Codex examples

- [codex_session.py](codex_session.py): multi-turn conversations.
- [codex_session_agentos.py](codex_session_agentos.py): sessions through AgentOS.
- [codex_mcp_tools.py](codex_mcp_tools.py): connect native MCP tools.
- [codex_structured_output.py](codex_structured_output.py): JSON Schema output.
- [background_cancel.py](background_cancel.py): background execution and cancellation.

Each exercise has its own setup and validation history in [TEST_LOG.md](TEST_LOG.md).

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
