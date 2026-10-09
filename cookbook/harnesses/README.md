# Coding harnesses on AgentOS

Run a coding harness through Agno, inspect its tools, then serve it through
AgentOS. Start with one provider: [Claude](claude/README.md) or
[Codex](codex/README.md). Both review the same small [shipping project](sample_project/README.md).

The harness owns its agent loop, tool execution and native context management.
Agno adapts its output to runs and events. AgentOS adds the HTTP API and run
storage used in this first exercise.

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

| Step | File in each provider folder | What to inspect |
|---|---|---|
| 1. First run | `basic.py` | An answer, Agno run ID and terminal status |
| 2. Compare the SDK | `native_sdk.py` | The same prompt/model through the native SDK, with its own session/thread ID |
| 3. Inspect code | `tools.py` | Text deltas, tool start/end events and actual file contents in tool results |
| 4. Serve it | `agent_os.py` | HTTP/SSE responses and a persisted run retrieved by run/session ID |

Start with `python cookbook/harnesses/claude/basic.py` or
`python cookbook/harnesses/codex/basic.py`. Every script is independent.
The tools exercise should explain fees of 8, 0 and 0 dollars for the three
orders. No editing of the sample project is required.

The basic and native SDK examples contain the policy in the prompt. They
establish a round trip, not file access. The tools example must actually read
the fixture. Assertions make failed/error runs exit unsuccessfully instead of
printing an error and passing the test.

## What this first set establishes

| Area | Current exercise and boundary |
|---|---|
| Text and tools | Live standalone streaming and HTTP streaming/non-streaming; SDK-specific details are translated, not exposed losslessly |
| Product history | `agent_os.py` saves Agno runs/tool results in a local SQLite file |
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

Both examples use bounded prompts. Claude additionally has SDK turn and dollar
budgets; Codex has no equivalent budget configured here. Native scripts time
out after 120 seconds, and the live test suite bounds subprocess/HTTP waits.
Those are test limits, not billing guarantees.

`PORT` changes the local server port. `HARNESS_STATE_DIR` changes the SQLite
directory; otherwise it is `tmp/harnesses/<provider>/` under your launch directory.
Stop the server before removing its disposable local state. That does not
remove SDK-native session files.

## Existing examples and the next exercises

The migration is incremental. Advanced
[Claude examples](../frameworks/claude-agent-sdk/README.md),
[Codex examples](../frameworks/codex/README.md), and the managed
[Antigravity integration](../frameworks/antigravity/README.md) retain their
existing paths for now. Their historical test logs do not imply verification
by this new suite.

[Framework adapters](../frameworks/README.md) cover LangGraph and DSPy, whose
state contracts differ from coding harnesses.

Next: native session recovery and storage failures; long conversations and
compaction; background/queue/disconnect/retry/multi-replica exercises; step
replay; skills/plugins/registry; interfaces and session-owned sandboxes.
These are follow-up topics, not guarantees made by this first set.
