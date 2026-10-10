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
python cookbook/frameworks/claude-agent-sdk/claude_basic.py
```

Inspect the answer and Agno run ID. An order of exactly 100 dollars qualifies
for free shipping. This prompt contains the policy, so no file read is needed.
The script uses `print_response(..., stream=True)`, which displays the terminal status and raises
on failed or cancelled runs, so errors exit nonzero.

For interactive use, Agno also provides formatted output:

```python
from agno.agents.claude import ClaudeAgent

agent = ClaudeAgent(model="claude-sonnet-5-5", tools=[])
agent.print_response("What is a Python context manager?", stream=True)
```

In an async application, use `await agent.aprint_response(..., stream=True)`. Both methods
return the final `RunOutput`; use `raise_on_error=False` only when you want to
handle failed or cancelled results yourself. See the shared
[3.2 migration notes](../README.md#adapter-api-changes-for-32).

## 2. Compare with the native SDK

```bash
python cookbook/frameworks/claude-agent-sdk/claude_native_sdk.py
```

The prompt, model and corresponding execution settings match `claude_basic.py`.
The native example iterates `query()` messages and checks `ResultMessage`.
The Agno adapter uses a per-run `ClaudeSDKClient`, wraps output in `RunOutput`,
and translates streaming messages into Agno events. Both delegate the actual
loop to Claude; Agno does not replace it.

The comparison is about API shape, not identical prose or latency. These
one-shot scripts do not configure an Agno database or establish durable resume.

Official reference: [Claude Python SDK](https://code.claude.com/docs/en/agent-sdk/python).

## 3. Watch actual tools

```bash
python cookbook/frameworks/claude-agent-sdk/claude_tools.py
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
python cookbook/frameworks/claude-agent-sdk/claude_agentos.py
```

In another terminal:

```bash
curl -fsS http://127.0.0.1:7777/health
curl -fsS http://127.0.0.1:7777/agents
curl --no-buffer -fsS http://127.0.0.1:7777/agents/claude-reviewer/runs \
  -F 'message=Read shipping.py and orders.json. Explain the fee for each order. Do not modify files.' \
  -F 'session_id=claude-shipping-review' -F 'stream=true'
```

This streams SSE. Use `stream=false` for a single JSON response. Run one provider
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
[existing transcript exercise](#durable-transcripts).

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
[TEST_LOG.md](TEST_LOG.md) for observations. Continue with the session, MCP and background examples below.


## More Claude examples

- [claude_session.py](claude_session.py): multi-turn conversations.
- [claude_session_agentos.py](claude_session_agentos.py): sessions through AgentOS.
- [claude_mcp_tools.py](claude_mcp_tools.py): connect native MCP tools.
- [transcript_store.py](transcript_store.py): inspect transcript mirroring and restoration.
- [background_cancel.py](background_cancel.py): background execution and cancellation.

Each exercise has its own setup and validation history in [TEST_LOG.md](TEST_LOG.md).

## Durable transcripts

Claude Code keeps each conversation as a JSONL transcript on the local disk of the machine that ran it. When `ClaudeAgent` has a database that supports transcript storage, every transcript line is also mirrored into the `agno_transcripts` table, and a later turn on any machine resumes the conversation from the database instead of the local file.

`transcript_store.py` runs the whole flow and prints the table after each step. Replica A runs a turn and stores a fact. Replica B is a second agent instance with a different working directory, so replica A's local transcript is invisible to it. It resumes from the database, answers from the stored conversation, and appends its own lines to the same transcript.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/transcript_store.py
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/transcript_store.py --postgres
```

The `--postgres` flag uses the container from `cookbook/scripts/run_pgvector.sh`. A normal `claude login` or `ANTHROPIC_API_KEY` is enough: for a store-backed resume the SDK writes the transcript into a temporary config directory and copies the caller's credentials into it, including macOS Keychain logins.

Use PostgreSQL in production. Transcript storage supports PostgresDb, AsyncPostgresDb, SqliteDb, and AsyncSqliteDb. `project_key` defaults to the agent id; set a stable tenant-specific value when sharing a database. Other database adapters retain local-file resume behavior. Workspace files are not persisted by this store.

The `agno_transcripts` table is created on first use. A development database that ran an earlier build of this feature has an older table shape and raises a schema mismatch; drop the table and it is recreated.

## Images and files

Claude Code reads files itself, so attachments reach it the way they reach a person at a terminal. `ClaudeAgent` writes each image or file passed to `run` / `arun` (or uploaded through the AgentOS API and UI) under `cwd/.agno/uploads/<run_id>/` and names the paths in the prompt; Claude opens them with its Read tool, which handles images and PDFs. The folder is removed when the run ends unless `keep_uploads=True`. The run's `input` records what was attached. Audio and video are rejected before the run starts, with a 400 or a `RunError` event through AgentOS, because Claude Code has no way to use them. The Read tool must be allowed for attachments to be useful.

```bash
.venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_media.py
```

## Background runs and cancellation

`background_cancel.py` serves the agent through AgentOS. Submit runs with `background=true`, poll the run endpoint, or use `stream=true` for indexed SSE. Runs continue after disconnects; the resume endpoint reads the configured event stream. Cancel through the run cancellation endpoint.

Run `background_cancel.py --verify` to start a real streamed turn, cancel after its first content event, and verify CANCELLED in the database. Multi-replica resume and cancellation require shared event-stream and cancellation-manager backends. Stored-event replay after the event-stream TTL is a follow-up.


### Transcript write failures

If the SDK exhausts transcript-store retries, the response remains completed and retains its content.
`RunOutput.metadata["warnings"]` contains a `transcript_persistence_failed` warning, also saved in run
history. Streaming callers receive a `CustomEvent` with the same `warning` object. The warning means
another replica may be unable to recover the complete conversation. The adapter does not reexecute
completed model work or tool side effects to repair the mirror.

### When transcripts stay on local disk

A database without transcript storage logs a warning once and the agent continues with the SDK's
local-disk transcripts, so resume works on the machine that ran the session. Transcript storage is also
skipped, with a warning, when `enable_file_checkpointing` is set in `options=ClaudeAgentOptions(...)`, because the SDK
does not allow the two together. A `session_store` supplied through these native `options` is used as is.
The legacy `options_kwargs` dictionary is deprecated; see the
[current configuration guide](#configure-claude-without-a-keyword-dictionary).
