# Framework integrations

Run a coding harness through Agno, inspect its tools, then serve it through
AgentOS. Start with one provider: [Claude](claude-agent-sdk/README.md) or
[Codex](codex/README.md). Both review the same small [shipping project](sample_project/README.md).

The harness owns its agent loop, tool execution and native context management.
Agno adapts its output to runs and events. AgentOS adds the HTTP API and run
storage used in this first exercise.

This directory also contains [LangGraph](langgraph/), [DSPy](dspy/),
[Antigravity](antigravity/README.md), and the [mixed-framework quickstart](00_quickstart/README.md).
Claude and Codex each keep their starting and advanced examples in one folder.

## Start here

Use a source checkout containing this cookbook. A package version alone does
not identify which unreleased adapter changes are present.

From the repository root:

```bash
uv venv .venvs/harnesses --python 3.12
source .venvs/harnesses/bin/activate
uv pip install -e 'libs/agno[os,sqlite]'
```

Then install and authenticate the SDK in the provider's README. You only need
the provider you choose. These scripts make real model calls. Use the same
interpreter for installation, examples and tests.

## Follow the same four steps with either provider

| Step | Claude | Codex | What to inspect |
|---|---|---|---|
| 1. First run | [claude_basic.py](claude-agent-sdk/claude_basic.py) | [codex_basic.py](codex/codex_basic.py) | Answer, run ID and terminal status |
| 2. Compare the SDK | [claude_native_sdk.py](claude-agent-sdk/claude_native_sdk.py) | [codex_native_sdk.py](codex/codex_native_sdk.py) | Same prompt/model through the native SDK |
| 3. Inspect code | [claude_tools.py](claude-agent-sdk/claude_tools.py) | [codex_tools.py](codex/codex_tools.py) | Streamed text, visible tools and actual file results |
| 4. Serve it | [claude_agentos.py](claude-agent-sdk/claude_agentos.py) | [codex_agentos.py](codex/codex_agentos.py) | HTTP/SSE and persisted runs |

Start with `python cookbook/frameworks/claude-agent-sdk/claude_basic.py` or
`python cookbook/frameworks/codex/codex_basic.py`. Every script is independent.
The tools exercise should explain fees of 8, 0 and 0 dollars for the three
orders. No editing of the sample project is required.

The basic and native SDK examples contain the policy in the prompt. They
establish a round trip, not file access. The tools example must actually read
the fixture. The basic examples use `print_response()`, which returns a `RunOutput` and
raises on errors or cancellation by default. The native SDK and Codex tools examples also check
terminal results explicitly; Claude tools use the same response printer. Failed runs exit unsuccessfully.

## What this first set establishes

| Area | Current exercise and boundary |
|---|---|
| Text and tools | Live standalone streaming and HTTP streaming/non-streaming; SDK-specific details are translated, not exposed losslessly |
| Product history | The AgentOS examples save Agno runs/tool results in a local SQLite file |
| Claude native state | With this SQLite adapter, native entries are mirrored through the Claude SDK session store; successful mirroring and cross-process recovery need their own tests |
| Codex native state | Agno stores the thread ID; native thread files remain in Codex's local storage |
| Durability | This set does not prove disconnect survival, durable queue acceptance, retries or crash recovery |
| Advanced SDK features | Compaction, subagents, skills, plugins, approvals and checkpoint branching are separate exercises |

Product history, native conversation state and workspace files are different
things. Saving a run does not establish recovery of all three. In the current
adapters, a missing native session can fall back to a new conversation seeded
with Agno history; that is not proof of native continuity.

Support limitations live here and in the provider READMEs. Fresh observations
live in [TEST_LOG.md](TEST_LOG.md); use [TEST_PROMPT.md](TEST_PROMPT.md) to reproduce them.

## Runtime boundaries

The server examples bind to `127.0.0.1`, have no authentication and use SQLite
for local development. Production requires explicit authorization, durable
storage and an execution/coordination topology appropriate to the product.
Neither a working directory nor a tool allowlist provides tenant isolation.

Both examples use bounded prompts. Native scripts time out after 120 seconds,
and the live test suite bounds subprocess/HTTP waits.
Those are test limits, not billing guarantees.

`PORT` changes the local server port. `HARNESS_STATE_DIR` changes the SQLite
directory; otherwise it is `tmp/harnesses/<provider>/` under your launch directory.
Stop the server before removing its disposable local state. That does not
remove SDK-native session files.

## Existing examples and the next exercises

The [Claude guide](claude-agent-sdk/README.md#more-claude-examples) and
[Codex guide](codex/README.md#more-codex-examples) include sessions, MCP tools,
background execution and other advanced examples. Their historical test logs
do not imply verification by the starting-example suite.

Next: native session recovery and storage failures; long conversations and
compaction; background/queue/disconnect/retry/multi-replica exercises; step
replay; skills/plugins/registry; interfaces and session-owned sandboxes.
These are follow-up topics, not guarantees made by this first set.


## Adapter API changes for 3.2

Configure built-in adapters with keywords, for example `ClaudeAgent(name="Reviewer",
model="claude-sonnet-5-5")`. Positional constructor arguments are no longer accepted.
Related fields are grouped in the constructor signature; keyword calls keep their meaning.
This applies to Claude, Codex, LangGraph, DSPy and Antigravity. Python 3.9 remains
supported by the adapter layer; each native SDK has its own Python requirements.


The integration is identified by read-only `agent.sdk`, selected by the agent class.
For example, Claude uses `"claude-agent-sdk"` and Codex uses `"codex"`. Neither `sdk`
nor `framework` is a constructor option. `agent.framework` remains a compatibility
alias. API metadata and new session metadata include both keys; existing transcript
storage namespaces and database columns keep their original names and values.

`print_response()` and `aprint_response()` return the final `RunOutput`, including
run ID, status and tools. Errors and cancellations are displayed explicitly and
raise by default. To inspect an unsuccessful result without raising:

```python
result = agent.print_response("Review the project", raise_on_error=False)
print(result.status)
```

The async equivalent is `result = await agent.aprint_response(...)`. Interactive
printing rejects `background=True`; call `arun(background=True)` directly for
background execution. Foreground streams yield event objects; background streams
yield SSE strings. With `yield_run_output=True`, either stream appends a terminal
`RunOutput`.

Separate `images`, `audio`, `videos` and `files` inputs are rejected by the current
adapters before work starts. Empty collections are accepted. This does not restrict
file reads through the harness's native tools; it prevents uploaded inputs from
being silently discarded. Media support needs an explicit adapter implementation.
