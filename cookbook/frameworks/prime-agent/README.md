# Prime Agent

Use [Prime Intellect's Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)
through the same external-agent API as Claude and Codex:

```python
from agno.agents.prime import PrimeAgent

agent = PrimeAgent(
    name="Prime Coder",
    cwd="/path/to/project",
    instructions="Explain your findings clearly. Ask before modifying files.",
)
run = agent.print_response("Summarize this project", stream=True)
print(run.run_id)
```

## Setup

Install and authenticate the `prime-agent` CLI following its repository's
instructions. Launch it once and use `/login` to configure a provider. No Python
SDK is needed. The adapter uses Prime's configured model and credentials by
default; `provider`, `model`, `thinking`, and `env` can override them.

The CLI must support `--mode json`, `--print`, and `--resume`. Compaction also
requires print-mode `/compact` support. Prime runs its own tools with the
permissions of the Agno process. Examples accept `PRIME_AGENT_CWD`.

## Supported API

| Capability | Prime integration |
| --- | --- |
| Calls and printing | `run`, `arun`, `print_response`, `aprint_response`; printers return the final run and raise on failure by default |
| Streaming | Text deltas, tool start/completion events, lifecycle events, optional terminal `RunOutput` |
| Tools | Prime's native Python REPL and tools; tool results retained in both run modes |
| Sessions | Native session IDs scoped by user and Agno session, optionally persisted in Agno's DB |
| Metrics | Reported input/output/cache tokens and cost, per-model usage, run timing, session totals |
| Background and cancellation | Shared `arun(background=True)` with a database; `cancel_run`/`acancel_run` interrupt the active CLI process |
| Retries | Shared `retries`, `delay_between_retries`, `exponential_backoff` |
| Compaction | `compact`/`acompact` run native `/compact` on an idle session |
| Attachments | `images` and `files` through native `@file` arguments; shared staging and cleanup |
| Skills | `skills=["/path/to/skill"]` maps to repeated `--skill`; `no_skills=True` disables discovery |
| Instructions | `instructions` and `append_system_prompt` supplement the prompt; `system_prompt` replaces it |
| Ephemeral runs | `ephemeral=True` disables native persistence and resume via `--no-session` |

Configuration is keyword-only. `agent.sdk` is `"prime-agent"` and `framework`
is a read-only alias, matching the other adapters. AgentOS uses the shared run,
session, streaming and metadata APIs.

Prime keeps its own native JSONL session files. It does not expose Claude's
native session-store hook, so the adapter does not mirror transcripts into the
database. Agno saves conversation runs and the native session ID. Keep the native
files available on the same host, or use a persistent `session_dir`, to resume
across restarts. Without a database, an explicit `session_id` resumes within the
adapter's lifetime. An expired or missing native session is reported as a CLI
failure. When no native ID exists, persisted Agno history is included in a fresh
prompt.

Metrics sum the assistant requests emitted during the run. Prime's
`totalTokens` includes cache tokens; input/output and cache fields retain
Prime's separate counts. Cost stays unset when Prime does not report it. These
figures do not claim to include subagent or compaction calls that Prime does not
emit as assistant usage in this stream.

Attachments are staged under `cwd/.agno/uploads/<run_id>/` and removed after the
run unless `keep_uploads=True`. Recent stored attachments are restored for later
turns. Native image input depends on the selected model and Prime's image limits.
Non-image `@file` inputs are read as UTF-8 text by Prime; PDFs and other binary
documents do not gain native document understanding. Remote URLs are passed as
references without being downloaded.

`compact` returns `False` when no native ID exists or Prime skips compaction with
a warning. CLI and compaction errors raise. A session with an active or pending
Agno run rejects compaction. Compaction updates native context; Agno's saved
history remains available.

## Unsupported options

The adapter does not expose Agno Python tools, native MCP-server configuration,
Claude permission modes/plugins, Codex sandbox/approval settings, or
provider-enforced `output_schema`. Audio/video uploads and native SDK input
objects are rejected. Prime manages its built-in subagents and automatic context
management internally; those do not acquire Claude/Codex checkpoint APIs here.

Cancellation terminates the print-mode CLI and its process group on POSIX. It
does not stop unrelated Prime daemon sessions. Background execution uses Agno's
shared process runtime and does not establish restart or multi-replica recovery.
Retries can repeat native tool side effects.

## Examples

| File | Purpose |
| --- | --- |
| `prime_basic.py` | Standalone streaming response |
| `prime_tools.py` | Read the shared sample project and inspect tool events |
| `prime_session.py` | Two turns with SQLite persistence and native resume |
| `prime_agentos.py` | AgentOS with Postgres persistence; requires `DATABASE_URL` |
| `prime_metrics.py` | Run and accumulated session metrics |
| `prime_compaction.py` | Manual native compaction and continuation |
| `prime_media.py` | Native image and text attachments |
| `prime_retries.py` | Retry configuration and ephemeral runs |
| `prime_async.py` | Async non-streaming runs and streaming response printing |
| `prime_background.py` | Background submission and polling the persisted terminal result |
| `prime_background_cancel.py` | Cancel after the first streamed text chunk and check stored status |
| `prime_skills.py` | Load the included local skill with automatic discovery disabled |
| `prime_ephemeral.py` | Persist and replay Agno history without native session IDs |
| `prime_session_recovery.py` | Recreate the adapter and verify native-session continuity |
| `prime_session_agentos.py` | Local SQLite AgentOS server for HTTP session testing |

```bash
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_basic.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_tools.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_session.py

export DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5532/ai
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_agentos.py
```

## Additional feature exercises

The standalone exercises include assertions, so an unexpected result fails the
script instead of looking like a successful demonstration:

```bash
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_async.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_background.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_background_cancel.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_skills.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_ephemeral.py
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_session_recovery.py
```

`prime_skills.py` includes a small fixture under
`fixtures/skills/cookbook-report/SKILL.md`. It checks that Prime follows the
skill's response instructions, using an explicit skill path and `no_skills=True`.
No external skill installation is needed.

`prime_background.py` polls until a saved run completes, fails or is cancelled.
`prime_background_cancel.py` requests cancellation after the first text chunk,
then checks both the terminal streamed run and its persisted cancelled status.
Both require the Python process to remain running. The ephemeral and recovery
examples use temporary SQLite databases. Recovery recreates the Python adapter
on the same host and checks the stored native ID and recalled fact.

For HTTP session continuity, start the local server:

```bash
.venvs/demo/bin/python cookbook/frameworks/prime-agent/prime_session_agentos.py
```

In another terminal, send two turns with the same user and session:

```bash
curl -sS http://127.0.0.1:7777/agents/prime-chat/runs \
  -F 'message=Remember the project codename is Cedar. Reply with OK.' \
  -F 'session_id=prime-http-demo' -F 'user_id=prime-demo-user' -F 'stream=false'

curl -sS http://127.0.0.1:7777/agents/prime-chat/runs \
  -F 'message=What is the project codename?' \
  -F 'session_id=prime-http-demo' -F 'user_id=prime-demo-user' -F 'stream=false'

curl -sS 'http://127.0.0.1:7777/sessions/prime-http-demo/runs?type=agent&user_id=prime-demo-user'
```

Expect completed run responses, the recalled codename, and saved runs labelled
with `metadata.sdk=prime-agent`. Add `-F 'stream=true'` to exercise SSE responses.
The local server uses SQLite and binds to localhost. `PORT` changes its port.

These make real model calls. Test status is recorded in `TEST_LOG.md`; the
unit tests and live examples remain unrun. Formatting and lint pass; full
static validation has failures in unchanged repository files.
