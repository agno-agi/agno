# Claude: SDK to AgentOS

Start with the [shared setup](../README.md#start-here), then install the tested
SDK version in that environment:

```bash
uv pip install 'claude-agent-sdk==0.2.165'
```

Authenticate through your existing Claude CLI login, or export
`ANTHROPIC_API_KEY` in your shell. Do not put credentials in these files.
The examples default to `claude-sonnet-4-6`; `CLAUDE_MODEL` overrides it.

## 1. Run the smallest example

```bash
python cookbook/harnesses/claude/basic.py
```

Inspect the answer and Agno run ID. An order of exactly 100 dollars qualifies
for free shipping. This prompt contains the policy, so no file read is needed.
The script checks terminal status and nonempty output. An error exits nonzero.

## 2. Compare with the native SDK

```bash
python cookbook/harnesses/claude/native_sdk.py
```

The prompt, model and corresponding execution settings match `basic.py`.
The native example iterates `query()` messages and checks `ResultMessage`.
The Agno adapter uses a per-run `ClaudeSDKClient`, wraps output in `RunOutput`,
and translates streaming messages into Agno events. Both delegate the actual
loop to Claude; Agno does not replace it.

The comparison is about API shape, not identical prose or latency. These
one-shot scripts do not configure an Agno database or establish durable resume.

Official reference: [Claude Python SDK](https://code.claude.com/docs/en/agent-sdk/python).

## 3. Watch actual tools

```bash
python cookbook/harnesses/claude/tools.py
```

This time the policy is not supplied in the prompt: the harness must read
`shipping.py` and `orders.json`. Observe text deltas and tool start/end events,
including the returned file contents. Expect fees of 8, 0 and 0 dollars.
The script checks that at least one tool succeeded; the live test also checks
fixture contents in the output. Inspect the final explanation yourself.

Only the SDK's `Read` tool is exposed, and `dontAsk` denies permission
requests instead of waiting for unattended approval. `allowed_tools` alone
does not remove other tools, so `options_kwargs["tools"]` specifies the actual
tool set. User/project settings are not loaded and ambient MCP configuration
is disabled. The working directory is a starting point, not a filesystem jail.

## 4. Serve the same review through AgentOS

```bash
python cookbook/harnesses/claude/agent_os.py
```

In another terminal:

```bash
curl -fsS http://127.0.0.1:7777/health
curl -fsS http://127.0.0.1:7777/agents
curl -fsS http://127.0.0.1:7777/agents/claude-reviewer/runs \
  -F 'message=Read shipping.py and orders.json. Explain the fee for each order. Do not modify files.' \
  -F 'session_id=claude-shipping-review' -F 'stream=false'
```

Repeat with `stream=true` and `curl --no-buffer` to see SSE. Run one provider
server at a time, or set `PORT=7778` for the second server.

Copy the returned `run_id` and read the stored result:

```bash
curl -fsS 'http://127.0.0.1:7777/agents/claude-reviewer/runs/RUN_ID?session_id=claude-shipping-review'
```

Agno stores product-facing run/tool data in `tmp/harnesses/claude/runs.db`.
The SQLite adapter also enables Claude's native transcript mirror.
A completed answer can still carry a `transcript_persistence_failed` warning;
inspect metadata before treating native state as durable. This exercise does
not validate cross-process restoration. See the
[existing transcript exercise](../../frameworks/claude-agent-sdk/README.md).

The local server has no authentication. Use PostgreSQL and explicit
authorization for production. Background jobs, disconnects and recovery are
follow-up exercises, not guarantees demonstrated here.

## Validate and continue

Use [TEST_PROMPT.md](../TEST_PROMPT.md) for reproducible live tests and
[TEST_LOG.md](TEST_LOG.md) for observations. The advanced examples retain their
existing paths during this incremental migration.
