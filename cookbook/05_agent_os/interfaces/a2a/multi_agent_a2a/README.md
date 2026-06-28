# Multi Agent A2A Cookbook

Three Agno servers and three SDK-client demos that prove an Agno-hosted A2A
endpoint speaks the **A2A 1.0** protocol — callable from the official
`a2a-sdk` client, [a2a-inspector](https://github.com/a2aproject/a2a-inspector),
Google ADK, LangGraph, or anything else that targets the 1.0 spec.

## Files

Servers (each is a standalone AgentOS exposing one specialist agent over A2A):

- `airbnb_agent.py` — Airbnb search specialist. Port **7774**.
- `weather_agent.py` — Weather forecast specialist. Port **7770**.
- `trip_planning_a2a_client.py` — Trip Planner orchestrator that talks to the two specialists via the official `a2a.client` API. Port **7777**.

Standalone SDK-client demos (no AgentOS — pure client scripts):

- `streaming_client_demo.py` — Connect to a running agent and iterate over a streaming `message/stream` response, printing each event.
- `agent_card_demo.py` — Fetch and pretty-print the v1-shaped AgentCard from a running server.

## Quick start

```bash
# Terminal 1
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/airbnb_agent.py

# Terminal 2
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/weather_agent.py

# Terminal 3 — the orchestrator (Agno agent using the a2a-sdk client as a tool)
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/trip_planning_a2a_client.py

# Terminal 4 — inspect the AgentCard advertised by the weather agent
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/agent_card_demo.py

# Terminal 5 — stream a real response over A2A
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/streaming_client_demo.py
```

## Why this works with any A2A 1.0 client

The Agno A2A interface emits standard A2A 1.0 wire format:

- AgentCard structure: `supportedInterfaces[]` with `protocolBinding: "JSONRPC"` and `protocolVersion: "1.0"`; `capabilities.extendedAgentCard`; v1 enum values like `ROLE_AGENT` and `TASK_STATE_COMPLETED`.
- Flat `Part` objects with member-presence discrimination (`text` / `url` / `raw` / `data`) and `mediaType` — no `kind` discriminator, no nested `FilePart`/`FileWithUri`/`FileWithBytes`.
- JSON-RPC method dispatch: every operation (`SendMessage`, `SendStreamingMessage`, …) is POSTed to the single URL advertised in `supportedInterfaces[0].url`. Old URL-style routes (`/v1/message:send`, etc.) are still mounted for backwards compatibility.
- Streaming events: token chunks stream as `TaskArtifactUpdateEvent` (with `append=true`); lifecycle/progress flows as `TaskStatusUpdateEvent`; the run ends with a single `Task` event carrying the full history. Agno never emits a mid-stream `Message` (which the v1 SDK treats as terminal). Stream closure is the completion signal — the v0.3 `final` flag is gone.
- JSON-RPC 2.0 envelope on every response.

Concretely: the same Agno server you point `trip_planning_a2a_client.py` at can also be debugged in the [a2a-inspector](https://github.com/a2aproject/a2a-inspector), called from a Google ADK agent, or consumed by anything else built on `a2a-sdk>=1.0`. Agno isn't a custom dialect — it's the spec.

## Prerequisites

- `.venvs/demo` set up via `./scripts/demo_setup.sh`.
- `a2a-sdk>=1.0` installed (`uv pip install -U "a2a-sdk>=1.0"`).
- Load environment variables with `direnv allow` (requires `.envrc`).
- The airbnb agent uses the OpenBNB MCP server; the weather agent uses `OpenWeatherTools` (set `OPENWEATHER_API_KEY`).
