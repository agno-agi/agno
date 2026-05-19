# A2A Cookbook

Examples for `interfaces/a2a` in AgentOS. Every server below exposes Agno
agents over the **A2A 1.0** protocol (`a2a-sdk>=1.0`) and is callable from
any A2A 1.0 client — the official `a2a-sdk` Python client,
[a2a-inspector](https://github.com/a2aproject/a2a-inspector), Google ADK,
LangGraph, etc.

## Files

- `basic.py` — Minimal A2A-exposed Agno Agent.
- `agent_with_tools.py` — Agent with WebSearch tools over A2A.
- `reasoning_agent.py` — Reasoning agent (emits reasoning step events over A2A streaming).
- `research_team.py` — A team of Agno agents exposed as a single A2A endpoint.
- `structured_output.py` — Agent returning a structured Pydantic response over A2A.
- `multi_agent_a2a/` — Three servers + three SDK-client demos showing an Agno orchestrator calling other A2A agents through `a2a.client`. See its README.

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
    client = create_client("http://localhost:7777/a2a/agents/agno-assist/v1")
    async with client:
        req = SendMessageRequest(message=Message(
            message_id=str(uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text="Hello!", media_type="text/plain")],
        ))
        async for resp in client.send_message(req):
            if resp.WhichOneof("payload") == "task":
                for entry in resp.task.history:
                    for p in entry.parts:
                        if p.WhichOneof("content") == "text":
                            print(p.text)

asyncio.run(main())
```

The AgentCard for any running example is at `GET <base>/.well-known/agent-card.json` and follows the v1 schema (`supportedInterfaces`, `capabilities`, `extendedAgentCard`, ...).

## Testing interactively

- **a2a-inspector** — Run `docker run -d -p 8080:8080 ghcr.io/a2aproject/a2a-inspector` (or build locally from [a2aproject/a2a-inspector](https://github.com/a2aproject/a2a-inspector)) and point it at `http://host.docker.internal:7777/a2a/agents/<agent-id>`. It validates the agent card against the spec and gives you a chat UI plus a raw JSON-RPC debug console.
- **SDK client** — See `multi_agent_a2a/streaming_client_demo.py` and `multi_agent_a2a/agent_card_demo.py` for runnable patterns.

## Prerequisites

- `.venvs/demo` set up via `./scripts/demo_setup.sh`.
- `a2a-sdk>=1.0` installed (`uv pip install -U "a2a-sdk>=1.0"`).
- Load environment variables with `direnv allow` (requires `.envrc`).
- Some examples require local services (Postgres, Redis, Slack, MCP servers, OpenWeather API key — see each example).
