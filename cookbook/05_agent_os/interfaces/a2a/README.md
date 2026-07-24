# A2A Cookbook

Examples for `interfaces/a2a` in AgentOS. Every server below exposes Agno
agents over the **A2A 1.0** protocol (`a2a-sdk>=1.0`) and is callable from
any A2A 1.0 client — the official `a2a-sdk` Python client,
[a2a-inspector](https://github.com/a2aproject/a2a-inspector), Google ADK,
LangGraph, etc.

## Files

- `basic.py` — Minimal A2A-exposed Agno Agent.
- `basic_agent/` — Self-contained server + client pair: `AgentOS(a2a_interface=True)` on one side, `A2AClient` on the other. Start here.
- `agent_with_tools.py` — Agent with WebSearch tools over A2A.
- `reasoning_agent.py` — Reasoning agent (emits reasoning step events over A2A streaming).
- `research_team.py` — A team of Agno agents exposed as a single A2A endpoint.
- `structured_output.py` — Agent returning a structured Pydantic response over A2A.
- `multi_agent_a2a/` — Three servers + SDK-client demos showing an Agno orchestrator calling other A2A agents through `A2AClient`. See its README.

## Quick start

Start any example, then talk to it from the official `a2a-sdk` client:

```bash
# Terminal 1: start the server
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/basic.py
```

```python
# Terminal 2: send a message using the canonical a2a-sdk client
import asyncio
from uuid import uuid4
from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest

async def main():
    client = await create_client("http://localhost:7777/a2a/agents/basic_agent")
    async with client:
        req = SendMessageRequest(message=Message(
            message_id=str(uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text="Hello!", media_type="text/plain")],
        ))
        # The SDK yields a stream of StreamResponse oneofs. Token chunks
        # arrive as `artifact_update` events; the final response arrives as a
        # `task` event with the full history.
        async for resp in client.send_message(req):
            kind = resp.WhichOneof("payload")
            if kind == "artifact_update":
                chunk = "".join(
                    p.text for p in resp.artifact_update.artifact.parts
                    if p.WhichOneof("content") == "text"
                )
                print(chunk, end="", flush=True)
            elif kind == "task":
                print()  # newline after final chunk

asyncio.run(main())
```

The AgentCard for any running example is at `GET <base>/.well-known/agent-card.json` and follows the v1 schema (`supportedInterfaces`, `capabilities`, `extendedAgentCard`, ...).

### Calling A2A agents from an Agno agent

To make an Agno agent the *client* side, use `A2AClient` — one instance
per remote agent, wrapping the official `a2a-sdk` client as agent tools. Tool
names carry the remote agent's URL slug, so multiple instances coexist:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.a2a import A2AClient

orchestrator = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[A2AClient(url="http://localhost:7777/a2a/agents/basic_agent")],
    instructions=["Use `send_message_to_basic_agent(message=...)` to delegate to the remote agent."],
)
```

See `cookbook/91_tools/a2a/` for a runnable version and
`multi_agent_a2a/trip_planning_a2a_client.py` for an orchestrator coordinating
multiple remote agents (one toolkit instance per specialist).

### Stream event shapes

The stream is ordered per the v1 spec:

1. `task` — the initial Task (state `SUBMITTED`), always the first event.
2. `status_update` — lifecycle events (working / completed / failed / cancelled). Metadata carries `agno_event_type` for tool calls, reasoning, memory updates, workflow steps, etc.
3. `artifact_update` — incremental text chunks of the agent's response. The first chunk creates the artifact (`append` unset), later chunks carry `append=true`, and a closing event carries `lastChunk=true`. Concatenate the text parts for a live token stream.
4. `status_update` with a terminal state, then a final `task` snapshot with the full `history` and any media artifacts.

`message` is reserved by the v1 spec as a terminal event; Agno's interface never emits one mid-stream (the SDK would otherwise stop iterating early). Consume streams by reacting to the terminal `status_update`/final `task` — not by assuming the first `task` event carries the answer.

## Testing interactively

- **a2a-inspector** — Run `docker run -d -p 8080:8080 ghcr.io/a2aproject/a2a-inspector` (or build locally from [a2aproject/a2a-inspector](https://github.com/a2aproject/a2a-inspector)) and point it at `http://host.docker.internal:7777/a2a/agents/<agent-id>`. It validates the agent card against the spec and gives you a chat UI plus a raw JSON-RPC debug console.
- **SDK client** — See `multi_agent_a2a/streaming_client_demo.py` and `multi_agent_a2a/agent_card_demo.py` for runnable patterns.

## Prerequisites

- `.venvs/demo` set up via `./scripts/demo_setup.sh`.
- `a2a-sdk>=1.0` installed (`uv pip install -U "a2a-sdk>=1.0"`).
- Load environment variables with `direnv allow` (requires `.envrc`).
- Some examples require local services (Postgres, Redis, Slack, MCP servers, OpenWeather API key — see each example).
