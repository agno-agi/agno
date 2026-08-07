# Remote Agents as Team Members

This cookbook demonstrates using `RemoteAgent` as team members, enabling distributed agent architectures where agents can run on different servers.

## Overview

A `RemoteAgent` is a proxy that connects to an agent running on a remote AgentOS server. When used as a team member, the team leader can delegate tasks to agents running anywhere on the network.

## Key Concepts

### RemoteAgent Basics

```python
from agno.agent.remote import RemoteAgent

remote_agent = RemoteAgent(
    base_url="http://remote-server:7778",  # AgentOS server URL
    agent_id="researcher-agent",            # Agent ID on remote server
    timeout=60.0,                           # Request timeout
)
```

### Important: Remote execution is opt-in

`RemoteAgent` talks to the **RemoteAccess interface** of the target AgentOS (mounted at
`/remote` by default). The server must explicitly expose the agent:

```python
from agno.os import AgentOS
from agno.os.interfaces.remote_access import RemoteAccess

agent_os = AgentOS(
    agents=[researcher, internal_agent],
    interfaces=[RemoteAccess(agents=[researcher])],  # only researcher is remotely callable
)
```

Agents not passed to the `RemoteAccess` interface return 404 for remote calls, even if
they are served on the AgentOS default API.

### Important: Async Only

**RemoteAgent only supports async methods.** Teams with RemoteAgent members must use:
- `team.arun()` instead of `team.run()`
- `team.aprint_response()` instead of `team.print_response()`

## Running the Example

1. **Start a remote AgentOS server that mounts the RemoteAccess interface:**
   ```bash
   python cookbook/05_agent_os/remote/server.py
   ```

2. **Run the cookbook:**
   ```bash
   python cookbook/03_teams/23_remote_agents/01_basic_remote_member.py
   ```

## Architecture

```
┌─────────────────┐     HTTP/REST      ┌─────────────────┐
│   Local Team    │ ←───────────────── │  Remote Server  │
│                 │   /remote/agents/   │                 │
│  ┌───────────┐  │   {id}/runs         │  ┌───────────┐  │
│  │ Leader    │  │ ─────────────────→  │  │Researcher │  │
│  └───────────┘  │                     │  └───────────┘  │
│        │        │                     │        │        │
│  ┌───────────┐  │                     │  Runs locally   │
│  │ Summarizer│  │                     │  on server      │
│  │ (local)   │  │                     │  (exposed via   │
│  └───────────┘  │                     │  RemoteAccess)  │
│        │        │                     └─────────────────┘
│  ┌───────────┐  │
│  │RemoteAgent│──┼── Proxy to remote
│  │ (proxy)   │  │
│  └───────────┘  │
└─────────────────┘
```

## How It Works

1. **Duck typing:** Team does not check `isinstance(member, RemoteAgent)` — it just calls `.arun()` on the member when delegating. Both `Agent` and `RemoteAgent` implement `arun()` with compatible signatures, so delegation to a remote member is indistinguishable from a local one.
2. **Async propagation:** `team.arun()` builds the async delegate tool, which calls `member.arun()`; the sync path would call `member.run()`, which `RemoteAgent` does not implement — hence the async-only constraint.
3. **HTTP transport:** `RemoteAgent.arun()` (see `libs/agno/agno/agent/remote.py`) posts the task to the remote server's `POST /remote/agents/{agent_id}/runs` endpoint and maps the response (or SSE event stream) back into the same `RunOutput`/`RunOutputEvent` objects a local run produces.
4. **Opt-in visibility:** the server-side `RemoteAccess` interface (see `libs/agno/agno/os/interfaces/remote_access/`) resolves agents only against the list it was constructed with, so agents not opted in are not remotely callable.
