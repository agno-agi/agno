# Claude: SDK to AgentOS

Start with the [shared setup](../README.md#start-here), then install the tested
SDK version in that environment:

```bash
uv pip install 'claude-agent-sdk==0.2.165'
```

Authenticate through your existing Claude CLI login, or export
`ANTHROPIC_API_KEY` in your shell. Do not put credentials in these files.
The examples use `claude-sonnet-5-5` directly.

## 1. Run the smallest example

```bash
python cookbook/harnesses/claude/basic.py
```

Inspect the answer and Agno run ID. An order of exactly 100 dollars qualifies
for free shipping. This prompt contains the policy, so no file read is needed.
The script uses `print_response()`, which displays the terminal status and raises
on failed or cancelled runs, so errors exit nonzero.

For interactive use, Agno also provides formatted output:

```python
from agno.agents.claude import ClaudeAgent

agent = ClaudeAgent(model="claude-sonnet-5-5", tools=[])
agent.print_response("What is a Python context manager?", stream=True)
```

In an async application, use `await agent.aprint_response(...)`. Both methods
return the final `RunOutput`; use `raise_on_error=False` only when you want to
handle failed or cancelled results yourself. See the shared
[3.2 migration notes](../README.md#adapter-api-changes-for-32).

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
`shipping.py` and `orders.json`. `print_response(..., stream=True)` displays
streaming text and a Tool Calls panel. Expect fees of 8, 0 and 0 dollars.
The returned `result.tools` retains the full tool results; the live test checks
those results contain the fixture data, rather than trusting the explanation.
Use `agent.run(..., stream=True)` when you need to handle individual events.

Only the SDK's `Read` tool is exposed, and `dontAsk` denies permission
requests instead of waiting for unattended approval. `allowed_tools` alone
does not remove other tools, so `tools=["Read"]` specifies the actual
built-in tool set. User/project settings are not loaded and ambient MCP configuration
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

## Configure Claude without a keyword dictionary

Use named parameters for ordinary configuration: `model`, `system_prompt`,
`cwd`, `tools`, `allowed_tools`, `disallowed_tools`, `permission_mode`,
`max_turns`, `max_budget_usd`, `mcp_servers`, `setting_sources`,
`strict_mcp_config`, `skills` and `plugins`. These retain the SDK's semantics.
For example, `skills` accepts exact skill names or `"all"`; if you explicitly
select `tools`, include `"Skill"` to make those skills invocable. Plugin
configurations use the native SDK's local plugin shape.

You can also reuse the SDK's typed options object:

```python
from claude_agent_sdk import ClaudeAgentOptions
from agno.agents.claude import ClaudeAgent

options = ClaudeAgentOptions(
    tools=["Read"],
    allowed_tools=["Read"],
    permission_mode="dontAsk",
    setting_sources=[],
    strict_mcp_config=True,
)
agent = ClaudeAgent(model="claude-sonnet-5-5", cwd="./my-project", options=options)
```

- Non-`None` named parameters override `options`. Empty lists/dictionaries,
  empty strings, zero and `False` are explicit overrides; `None` inherits.
- Agno copies configuration containers per run. It does not deep-copy native
  callbacks, MCP server instances or session-store objects.
- Use `run`/`arun` with `session_id` and `stream` for Agno conversations and
  streaming. Native `resume`, `session_id`, `continue_conversation` and
  `fork_session` cannot select a different conversation through `options`.
  Conflicting `include_partial_messages` and raw CLI lifecycle flags raise
  errors rather than silently overriding Agno's run settings.
- A native `session_store` supplied through `options` takes precedence over
  Agno's transcript mirror. `enable_file_checkpointing=True` disables that
  mirror because the SDK cannot combine the two. These options do not change
  where Agno saves product-facing runs.

`options_kwargs` is deprecated. Existing dictionaries still work and emit a
`DeprecationWarning`; they retain their old precedence over named parameters.
Do not pass both forms. When migrating to `options=ClaudeAgentOptions(...)`,
remove duplicate settings or place the intended override in a named parameter.
Native session/streaming conflicts are rejected for the legacy form too.

## Validate and continue

Use [TEST_PROMPT.md](../TEST_PROMPT.md) for reproducible live tests and
[TEST_LOG.md](TEST_LOG.md) for observations. The advanced examples retain their
existing paths during this incremental migration.
