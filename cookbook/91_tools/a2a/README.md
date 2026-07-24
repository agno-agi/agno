# A2AClient Cookbook

`A2AClient` is the toolkit that lets an Agno agent **call a remote A2A
1.0 agent** as a tool. One toolkit instance binds one remote agent; it wraps
the official `a2a-sdk` Python client, so the same Agno code can talk to any
A2A 1.0 server on the wire.

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.a2a import A2AClient

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[A2AClient(url="http://localhost:7777/a2a/agents/basic_agent")],
)
agent.print_response("Ask the remote agent to say hello.")
```

Each instance exposes two operations, named after the remote agent's URL slug
so several instances can coexist on one Agno agent:

- `send_message_to_<slug>(message) -> str` — Send a message, get the agent's final response text.
- `get_<slug>_card() -> str` — Fetch the agent's `/.well-known/agent-card.json` so the LLM can discover capabilities first.

`url` is the **base URL** of the agent (everything up to but not including
`/.well-known/...`). The SDK resolves the agent card automatically. To talk
to several remote agents, give each its own instance:

```python
weather = A2AClient(url="http://localhost:7770/a2a/agents/weather-reporter-agent")
airbnb = A2AClient(url="http://localhost:7774/a2a/agents/airbnb-search-agent")
agent = Agent(model=OpenAIResponses(id="gpt-5.5"), tools=[weather, airbnb])
# -> send_message_to_weather_reporter_agent, send_message_to_airbnb_search_agent, ...
```

The toolkit connects lazily on first use. For explicit lifecycle management
(resolve the card up front, reuse one connection, enrich tool descriptions
from the card), use `await toolkit.connect()` / `await toolkit.close()` or
`async with toolkit:`.

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

`A2AClient` works against any A2A 1.0 base URL — that's the point of the
protocol. Today, however, most Python agent frameworks still ship `a2a-sdk`
0.3.x:

- **Google ADK** (`google-adk`) — pinned to `a2a-sdk<1.0`; v1 upgrade tracked in [adk-python#5056](https://github.com/google/adk-python/issues/5056).
- **Microsoft Agent Framework** — A2A 1.0 lives in the .NET packages; the Python build hasn't shipped v1 yet.
- **LangGraph / LangChain Agent Server** — exposes `/a2a/{assistant_id}` but uses the v0.3 method naming.

When any of these upgrade, point `A2AClient` at their base URL and it'll
just work — same toolkit, no Agno changes.

A note on safety: a remote agent's response flows into the orchestrator's
prompt and is therefore a prompt-injection vector. Only target endpoints
you trust.

## How it works

`A2AClient` is async-native. Under the hood:

1. On connect (explicit or lazy on first call), the `a2a-sdk` resolves the agent card and opens a persistent client with the right transport (JSON-RPC over HTTP+JSON for Agno servers). Sync tool variants run a one-shot client per call instead.
2. `send_message_to_<slug>` streams: chunks arrive as `artifact_update` events, the run completes with a final `task` event. The toolkit accumulates the chunks and prefers the terminal task's full text for its return value; FAILED/CANCELED/REJECTED terminal states come back as explicit errors.
3. `get_<slug>_card` returns a pretty-printed JSON of the v1 AgentCard so the LLM can read agent metadata directly.

Errors (connection refused, timeouts, malformed responses) are caught and
returned as a short string starting with `Error talking to ...` or
`Error fetching agent card from ...`, so the LLM can decide how to react
rather than the tool throwing.

## Prerequisites

- `pip install -U "a2a-sdk>=1.0"` (already in `agno[a2a]`).
- `OPENAI_API_KEY` for the orchestrator agent in the example.
