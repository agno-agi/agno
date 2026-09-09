# Remote components

`RemoteAgent`, `RemoteTeam`, and `RemoteWorkflow` let one Python process compose
components hosted elsewhere. This lesson compares the native AgentOS protocol
with A2A REST and JSON-RPC, uses remote Agents as Team members, and finishes
with one AgentOS gateway over all three transports.

## Files

| File | What it teaches |
|---|---|
| `01_remote_agent.py` | Await and stream an Agent hosted on another AgentOS. |
| `02_remote_team_and_workflow.py` | Run a remote Team and Workflow through the native AgentOS protocol. |
| `03_remote_via_a2a.py` | Compare an Agno A2A REST peer with a Google ADK JSON-RPC peer. |
| `04_remote_as_team_member.py` | Delegate one Team run to AgentOS and A2A remote members. |
| `05_gateway.py` | Serve local, AgentOS, Agno A2A, and Google ADK components behind one AgentOS. |
| `06_remote_auth.py` | Supply a per-call Bearer credential with `auth_token`. |
| `servers/agentos_server.py` | Host two Agents, one Team, and one Workflow on port 7780. |
| `servers/a2a_server.py` | Host one Agno Agent through A2A REST on port 7781. |
| `servers/adk_server.py` | Host one Google ADK Agent through A2A JSON-RPC on port 8001. |

## Prerequisites

Set up the demo environment and export provider keys:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
```

The demo environment includes Agno's A2A dependency. Google ADK currently
requires older OpenTelemetry and WebSocket versions than the shared demo
environment. Run that one server in an isolated `uv` environment so its
dependencies cannot downgrade the Agno environment:

```bash
uv run --isolated \
  --with google-adk \
  --with "a2a-sdk[http-server]>=0.3.0,<1.0" \
  --with uvicorn \
  cookbook/05_agent_os/20_remote/servers/adk_server.py
```

These examples use SQLite under `tmp/`. They do not require Postgres, a vector
database, or an external search service.

## Port and entity map

| Process | Port | Entities |
|---|---:|---|
| `servers/agentos_server.py` | 7780 | `assistant-agent`, `researcher-agent`, `research-team`, `qa-workflow` |
| `servers/a2a_server.py` | 7781 | `a2a-assistant` |
| `servers/adk_server.py` | 8001 | `facts_agent` |
| `05_gateway.py` | 7777 | `gateway-agent` plus all remote entities |

Start the three upstream servers in this order, one terminal per command:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/servers/agentos_server.py
```

```bash
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/servers/a2a_server.py
```

```bash
uv run --isolated \
  --with google-adk \
  --with "a2a-sdk[http-server]>=0.3.0,<1.0" \
  --with uvicorn \
  cookbook/05_agent_os/20_remote/servers/adk_server.py
```

Wait for the AgentOS health routes and the Google ADK Agent card before
starting the gateway. Gateway construction reads remote configuration and
Agent cards, so all three upstreams must already be available.

## Run the clients

With the required servers running:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/01_remote_agent.py
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/02_remote_team_and_workflow.py
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/03_remote_via_a2a.py
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/04_remote_as_team_member.py
```

The server requirements are:

| Example | Required upstreams |
|---|---|
| `01_remote_agent.py` | AgentOS 7780 |
| `02_remote_team_and_workflow.py` | AgentOS 7780 |
| `03_remote_via_a2a.py` | Agno A2A 7781 and Google ADK 8001 |
| `04_remote_as_team_member.py` | AgentOS 7780 and Agno A2A 7781 |
| `05_gateway.py` | All three |
| `06_remote_auth.py` | Secured AgentOS 7780 |

Remote components are asynchronous. Await a complete run, or iterate a stream
directly:

```python
response = await remote_agent.arun("Hello")

async for event in remote_agent.arun("Hello", stream=True):
    ...
```

There is no synchronous `run()` or `print_response()` counterpart on
`RemoteAgent`, `RemoteTeam`, or `RemoteWorkflow`.

## Run the gateway

After all three upstreams are ready:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/05_gateway.py
```

The gateway exposes one normal AgentOS API at `http://127.0.0.1:7777`. Its
`/config` response contains the local `gateway-agent`, three remote Agents,
the remote Team, and the remote Workflow. Runs sent to those entity IDs are
forwarded through their configured transports.

## Choose the right client

- Use `RemoteAgent`, `RemoteTeam`, or `RemoteWorkflow` with the default
  `protocol="agentos"` when the peer is AgentOS and native run, session, and
  configuration semantics matter. Pass the server root plus the entity ID.
- Use `RemoteAgent(protocol="a2a")` when an A2A entity should behave like a
  composable Agno Agent. For Agno REST, pass the full entity root. For Google
  ADK JSON-RPC, pass the server root and set `a2a_protocol="json-rpc"`.
- Use the lower-level `A2AClient` from `15_a2a` when the application needs
  protocol task IDs, context IDs, Agent cards, or raw A2A stream events.

`get_agent_config()` on an A2A RemoteAgent returns a small AgentOS-compatible
view derived from its Agent card. The current JSON-RPC client sends every
request to the RPC root, including card discovery; Google ADK serves its card
at `/.well-known/agent-card.json`. Consequently the ADK RemoteAgent falls back
to its configured ID and a generic description. `03_remote_via_a2a.py`
demonstrates card-derived introspection with the Agno REST peer and uses the
ADK peer for JSON-RPC execution.

## Authenticated remote runs

Stop the public AgentOS backend, then restart it with a shared development key:

```bash
export OS_SECURITY_KEY=cookbook-remote-key
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/servers/agentos_server.py
```

In another terminal with the same environment:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/20_remote/06_remote_auth.py
```

`auth_token` adds `Authorization: Bearer <value>` to that run. Remote
configuration helpers and sync metadata properties do not accept a token, so
the secured mode is intentionally a direct-run example. Restart the backend
without `OS_SECURITY_KEY` before running the gateway.

## Current remote boundaries

Basic remote calls and HTTP streaming are supported. AgentOS gateway routes do
not make every local lifecycle feature transparent: background execution,
run polling and listing, checkpoints, resumable streams, and remote Workflow
continuation over WebSocket are not supported. A2A remote components also do
not support AgentOS continuation or cancellation semantics. A completed
non-streaming A2A response currently maps its content correctly but retains the
`RUNNING` status supplied while the A2A task was in flight; use the returned
content rather than AgentOS polling at that boundary.

Google ADK's A2A adapter is experimental and emits corresponding warnings at
startup. The isolated command keeps those dependencies and warnings scoped to
the ADK server.
