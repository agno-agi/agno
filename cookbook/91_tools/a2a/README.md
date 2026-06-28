# A2AClientTools Cookbook

`A2AClientTools` is the toolkit that lets an Agno agent **call any A2A 1.0
agent** as a tool. It wraps the official `a2a-sdk` Python client, so the
same Agno code can talk to any A2A 1.0 server on the wire.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.a2a import A2AClientTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[A2AClientTools(default_agent_url="http://localhost:7777/a2a/agents/basic_agent")],
)
agent.print_response("Ask the remote agent to say hello.")
```

The toolkit exposes two operations to the LLM:

- `send_message(agent_url, message) -> str` — Send a message, get the agent's final response text.
- `get_agent_card(agent_url) -> str` — Fetch the agent's `/.well-known/agent-card.json` so the LLM can discover capabilities first.

`agent_url` is the **base URL** of the agent (everything up to but not
including `/.well-known/...`). The SDK resolves the agent card automatically.
Set `default_agent_url` at init time to skip passing it every call.

## Example: Agno → Agno

`01_call_agno_a2a_agent.py` — boot any of the AgentOS A2A interface cookbooks
first, then run this. Demonstrates the toolkit speaking A2A 1.0 against a
real Agno-hosted A2A server.

```bash
# Terminal 1
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/basic.py

# Terminal 2
.venvs/demo/bin/python cookbook/91_tools/a2a/01_call_agno_a2a_agent.py
```

Other interface cookbooks worth trying as the remote target:
`agent_with_tools.py`, `reasoning_agent.py`, `research_team.py`,
`structured_output.py`, or the specialists in `multi_agent_a2a/`.

## Cross-framework interop — coming when the ecosystem catches up

`A2AClientTools` works against any A2A 1.0 base URL — that's the point of the
protocol. Today, however, most Python agent frameworks still ship `a2a-sdk`
0.3.x:

- **Google ADK** (`google-adk`) — pinned to `a2a-sdk<1.0`; v1 upgrade tracked in [adk-python#5056](https://github.com/google/adk-python/issues/5056).
- **Microsoft Agent Framework** — A2A 1.0 lives in the .NET packages; the Python build hasn't shipped v1 yet.
- **LangGraph / LangChain Agent Server** — exposes `/a2a/{assistant_id}` but uses the v0.3 method naming.

When any of these upgrade, point `A2AClientTools` at their base URL and it'll
just work — same toolkit, no Agno changes.

A note on safety: a remote agent's response flows into the orchestrator's
prompt and is therefore a prompt-injection vector. Only target endpoints
you trust.

## How it works

`A2AClientTools` is async-native. Under the hood:

1. `create_client(agent_url)` from `a2a-sdk` resolves the agent card and picks the right transport (JSON-RPC over HTTP+JSON for Agno servers).
2. `send_message` streams: chunks arrive as `artifact_update` events, the run completes with a final `task` event. The toolkit accumulates the chunks and prefers the final task's full text for its return value.
3. `get_agent_card` returns a pretty-printed JSON of the v1 AgentCard so the LLM can read agent metadata directly.

Errors (connection refused, timeouts, malformed responses) are caught and
returned as a short string starting with `Error talking to ...` or
`Error fetching agent card from ...`, so the LLM can decide how to react
rather than the tool throwing.

## Prerequisites

- `pip install -U "a2a-sdk>=1.0"` (already in `agno[a2a]`).
- `OPENAI_API_KEY` for the orchestrator agent in the example.
