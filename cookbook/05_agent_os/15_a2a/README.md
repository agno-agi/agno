# A2A

A2A is the protocol-facing surface for one AgentOS entity to discover and call
another. This lesson covers both sides: serving Agents and Teams under the
`/a2a` namespace, and consuming those endpoints with Agno's first-party
`A2AClient`. It finishes with a three-server topology in which one Agent calls
two specialist Agents over A2A.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Expose one persistent Agent with `a2a_interface=True`. |
| `client.py` | Send, stream, preserve multi-turn context, and handle an unavailable server with `A2AClient`. |
| `agent_card.py` | Read stable Agent card identity and endpoint fields with the sync and async client APIs. |
| `team.py` | Expose, discover, and call a Team under `/a2a/teams`. |
| `multi_agent/weather_agent.py` | Serve the OpenWeather-backed specialist on port 7782. |
| `multi_agent/airbnb_agent.py` | Serve the OpenBNB MCP-backed specialist on port 7783. |
| `multi_agent/trip_planning_a2a_client.py` | Use async A2A client tools to orchestrate both specialists, then expose the planner on port 7779. |

## Prerequisites

Install the demo environment and export an OpenAI key:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

The demo environment includes the `agno[a2a]` extra. The multi-agent example
has two additional requirements:

- `weather_agent.py` needs `OPENWEATHER_API_KEY`.
- `airbnb_agent.py` needs Node.js, `npx`, and internet access so it can run
  `@openbnb/mcp-server-airbnb`.

`client.py` and `agent_card.py` do not call a model directly, but both require
`basic.py` to be running.

## Serve and call an Agent

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/basic.py
```

Then use the first-party client and card reader:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/client.py
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/agent_card.py
```

`a2a_interface=True` exposes all Agents, Teams, and Workflows registered with
that AgentOS. Use an explicit interface such as
`interfaces=[A2A(agents=[public_agent])]` when only selected entities should be
served or the interface needs custom tags.

The modern Agent routes are:

| Operation | Route |
|---|---|
| Discover | `GET /a2a/agents/{id}/.well-known/agent-card.json` |
| Send | `POST /a2a/agents/{id}/v1/message:send` |
| Stream | `POST /a2a/agents/{id}/v1/message:stream` |
| Get task | `POST /a2a/agents/{id}/v1/tasks:get` |
| Cancel task | `POST /a2a/agents/{id}/v1/tasks:cancel` |

For the REST-style first-party client, pass the entity root as `base_url`, for
example:

```python
client = A2AClient(
    "http://127.0.0.1:7779/a2a/agents/a2a-assistant"
)
```

`send_message()` and `stream_message()` are asynchronous. A completed
`TaskResult` already exposes the response as `.content`; no manual JSON-RPC
unwrapping is needed. Pass a returned `.context_id` to the next call to keep
the same AgentOS session. Card discovery has both a synchronous
`get_agent_card()` method and an asynchronous `aget_agent_card()` method.

## Serve and call a Team

Stop `basic.py`, because standalone A2A examples share port 7779, then start
the Team:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/team.py
```

In another terminal:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/team.py --demo
```

Teams use the same protocol shape under their own namespace:

- `GET /a2a/teams/{id}/.well-known/agent-card.json`
- `POST /a2a/teams/{id}/v1/message:send`
- `POST /a2a/teams/{id}/v1/message:stream`
- `POST /a2a/teams/{id}/v1/tasks:get`
- `POST /a2a/teams/{id}/v1/tasks:cancel`

## Run the multi-agent topology

Start the services in this order, one terminal per command:

```bash
export OPENWEATHER_API_KEY=...
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/weather_agent.py
```

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/airbnb_agent.py
```

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/trip_planning_a2a_client.py
```

The topology is:

| Service | Port | Entity root |
|---|---:|---|
| Trip planner | 7779 | `/a2a/agents/trip-planner` |
| Weather specialist | 7782 | `/a2a/agents/weather-agent` |
| Airbnb specialist | 7783 | `/a2a/agents/airbnb-agent` |

With all three servers running, call the planner from a fourth terminal:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/trip_planning_a2a_client.py --demo
```

The planner's two async tools use `A2AClient`, check the downstream task
status, and consume `TaskResult.content`. The weather and Airbnb Agents remain
independently discoverable and callable.

## Choosing an A2A entry point

- Use `a2a_interface=True` or `A2A(...)` in this lesson to **serve** a local
  AgentOS entity over A2A.
- Use `A2AClient` in this lesson for direct protocol calls, task metadata,
  streaming events, and explicit context threading.
- Use `RemoteAgent(protocol="a2a")` in `20_remote` when a remote A2A entity
  should behave like a composable Agent inside another Agent or Team.
