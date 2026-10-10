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
| `external_agent.py` | Expose, discover, and call an external Codex Agent under `/a2a/agents`. |
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

The explicit interface also takes the settings an Agent card carries:

| Setting | What it does |
|---|---|
| `base_url` | Public URL the cards advertise. Set it behind a proxy; it defaults to the URL the request came in on. |
| `security_schemes` | How a client must authenticate. AgentOS fills it in when it requires a token. |
| `provider` | Organization serving the entities. |
| `documentation_url`, `icon_url` | Links the cards carry. |
| `enable_v0_3_compat` | Also serve A2A v0.3 clients on the same endpoint. On by default. |

With authorization enabled, reading a card or a task requires the `read`
scope and sending a message or cancelling a task requires the `run` scope.
Both the global scope (for example `agents:read`) and a per-agent scope such
as `agents:{id}:read` are accepted, under any prefix.

Each Agent is served on two routes:

| Operation | Route |
|---|---|
| Discover | `GET /a2a/agents/{id}/.well-known/agent-card.json` |
| A2A endpoint | `POST /a2a/agents/{id}` |

The A2A endpoint speaks JSON-RPC. The method in the request body selects the
operation:

| Operation | A2A v1.0 method | A2A v0.3 method |
|---|---|---|
| Send | `SendMessage` | `message/send` |
| Stream | `SendStreamingMessage` | `message/stream` |
| Get task | `GetTask` | `tasks/get` |
| Cancel task | `CancelTask` | `tasks/cancel` |

A2A v1.0 methods must carry the `A2A-Version: 1.0` header. A2A v0.3 methods
need no header, so standard A2A v0.3 clients (for example ones built on
`a2a-sdk` 0.3) keep working. The Agent card lists both versions under
`supportedInterfaces`.

### Upgrading from the A2A v0.3 interface

- The `/v1/message:send`, `/v1/message:stream`, `/v1/tasks:get` and
  `/v1/tasks:cancel` routes are gone. Every operation is sent to the entity's
  A2A endpoint, `POST /a2a/agents/{id}`.
- Upgrade the server and `A2AClient` together. An `A2AClient` from an earlier
  Agno release calls the removed routes, and this `A2AClient` does not talk to
  an earlier Agno A2A server.
- The `a2a` extra now requires `a2a-sdk>=1.2.2`.
- Responses carry the answer in the task `artifacts`. Streams send
  `artifact-update` events instead of `message` events, and end the answer
  with one event that carries the full response.
- An Agent, Team or external agent with a database runs every message as a
  background run: the run is stored before it starts, so any replica can read
  the task, and it does not depend on the request that started it. A message
  sent without waiting for the result returns the submitted task with status
  200; read it with `GetTask`. Subscribing to a task, and cancelling it without
  a shared cancellation manager, work on the replica running it. A run
  interrupted by a crash stays `working`. Background runs share one limit per
  process (`AGNO_BACKGROUND_MAX_CONCURRENCY`, 32 by default); a message over
  the limit waits as `submitted`. `ListTasks` lists every stored run of the
  entity for the caller, including runs started outside A2A.
- A Workflow, or an entity without a database, runs in the server process. Its
  run is stored when it ends, and a run that is still going when the server
  restarts is lost.
- `A2AClient` sends requests to its `base_url`, whatever URL the Agent card
  advertises. If a server's endpoint is not at the URL its card is served
  from, pass the endpoint as `base_url`; the client then assumes A2A v1.0.
- `AgentCard.capabilities` returned by `A2AClient.get_agent_card()` is a dict
  instead of a list.
- An unknown task is reported as a JSON-RPC error (`TaskNotFound`) instead of
  an HTTP 404.
- `RemoteAgent(a2a_protocol=...)` and `A2AClient(protocol=...)` are deprecated.
  The protocol is negotiated from the Agent card.

For the first-party client, pass the entity root as `base_url`, for example:

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
- `POST /a2a/teams/{id}`

## Serve and call an external Agent

`external_agent.py` needs the Codex CLI and the `openai-codex` package. Start
the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/external_agent.py
```

In another terminal:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/15_a2a/external_agent.py --demo
```

External agents such as `CodexAgent` and `ClaudeAgent` are served on the same
routes as native Agents. The AgentOS database stores each run before it
starts, so the demo reads the finished task back with `get_task`.

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
