# Hermes through Agno

Use Nous Research's Hermes agent through the same `run()`, `arun()`,
`print_response()` and AgentOS APIs as the Claude and Codex adapters.
Hermes runs its native model and tools; Agno translates callbacks into run
events and stores conversation history and tool results.

## Setup

Hermes currently documents a source environment rather than a supported wheel
or source distribution. Follow its [Python library guide](https://hermes-agent.nousresearch.com/docs/guides/python-library)
and use a Python version supported by your Hermes checkout.

From your Hermes checkout, activate its environment and install this Agno checkout:

```bash
export AGNO_CHECKOUT=/absolute/path/to/agno
cd /absolute/path/to/hermes-agent
source ./activate
uv pip install --python "$(command -v python)" -e "$AGNO_CHECKOUT/libs/agno[os,sqlite]"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
```

Keep that environment active when running the cookbooks. `run_agent.AIAgent`
must be importable by that interpreter. Configure Hermes's provider credentials
as described in its guide (for example `OPENROUTER_API_KEY`), or pass
`provider`, `api_key` and `base_url` to `HermesAgent`.
`HERMES_MODEL` optionally overrides Hermes's configured model in these examples.
There is no new mandatory Hermes dependency on the Agno package.

## Examples

| File | Demonstrates |
|---|---|
| [hermes_basic.py](hermes_basic.py) | First streaming response with tools disabled |
| [hermes_native_sdk.py](hermes_native_sdk.py) | Equivalent prompt through native `AIAgent` |
| [hermes_tools.py](hermes_tools.py) | Native file tools with visible tool events |
| [hermes_session.py](hermes_session.py) | Two turns using stored Hermes messages |
| [hermes_agentos.py](hermes_agentos.py) | AgentOS HTTP/SSE and local SQLite storage |

```bash
python "$AGNO_CHECKOUT/cookbook/frameworks/hermes/hermes_basic.py"
python "$AGNO_CHECKOUT/cookbook/frameworks/hermes/hermes_agentos.py"
```

Run from the Agno repository root if you want the relative SQLite files under
its `tmp/` directory. Keep the Hermes checkout on `PYTHONPATH` in that case.

With the server running:

```bash
curl -N http://127.0.0.1:7777/agents/hermes-reviewer/runs \
  -F 'message=Read shipping.py and explain the shipping fee rules.' \
  -F 'session_id=shipping-review' \
  -F 'stream=true'
```

Use `stream=false` for a JSON response. Agent and session metadata use
`sdk="hermes"`. The server binds to loopback and has no authentication;
SQLite is only for local development. Configure PostgreSQL and authorization
for production.

## Configuration

```python
from agno.agents.hermes import HermesAgent

agent = HermesAgent(
    name="Hermes Researcher",
    enabled_toolsets=["web"],
    instructions="Cite your sources and be concise.",
    max_iterations=20,
    native_options={"max_tokens": 2048},
)

response = await agent.arun("Research this topic", session_id="research", user_id="alice")
```

`enabled_toolsets=[]` explicitly disables native toolsets. `None` keeps Hermes's
defaults. Named settings take precedence by rejecting conflicting entries in
`native_options`. Callbacks, native session identity and native database wiring
are reserved for the adapter. Memory and background review default to disabled;
set `skip_memory=False` or `skip_background_review=False` to opt in.

## Conversation and runtime boundaries

- Reuse the `HermesAgent` adapter. Every turn uses a separate native `AIAgent`
  because Hermes instances are not safe to share across concurrent calls.
  The blocking native API runs in a dedicated worker; callbacks cross to the
  asyncio loop through a queue.
- With `db`, the adapter saves Hermes's returned messages and native identity in
  `session_data.hermes_conversation`. Recreating the adapter replays those messages.
  Without `db`, messages live only on the adapter, keyed by user and session.
  This is history replay, not restoration of a running Hermes process or tool environment.
- Text deltas and tool start/completion callbacks become Agno events. Tool results
  missing a completion callback are recovered from the current turn's transcript.
  Non-streaming responses use the native final answer. Streams retain native commentary;
  provider output transforms can make the final reply differ from already delivered text.
- Reported token totals and estimated cost populate run/session metrics. A fresh
  native instance keeps the returned counters scoped to the current turn.
- `cancel_run()` / `acancel_run()` request Hermes interruption. Closing a stream
  also requests interruption, and cleanup waits for its worker to finish. Cancellation
  is cooperative; configure provider/tool timeouts in Hermes for blocked operations.
- `cwd` is a workspace setting, not filesystem isolation. Hermes's home, credentials,
  plugins and native memory remain process configuration. The file toolset includes
  writes; the example's instruction to read only is not an enforced permission policy.
- Uploaded media, provider-enforced `output_schema`, native compaction APIs and
  checkpoint continuation are not exposed by this adapter.

See [TEST_LOG.md](TEST_LOG.md) for the current verification status.
