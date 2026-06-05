# Remote Agents as Team Members

This cookbook demonstrates using `RemoteAgent` as team members, enabling distributed agent architectures where agents can run on different servers.

## Overview

A `RemoteAgent` is a proxy that connects to an agent running on a remote AgentOS server. When used as a team member, the team leader can delegate tasks to agents running anywhere on the network.

## Key Concepts

### RemoteAgent Basics

```python
from agno.agent.remote import RemoteAgent

remote_agent = RemoteAgent(
    base_url="http://remote-server:7777",  # AgentOS server URL
    agent_id="explorer",                    # Agent ID on remote server
    timeout=60.0,                           # Request timeout
)
```

### Important: Async Only

**RemoteAgent only supports async methods.** Teams with RemoteAgent members must use:
- `team.arun()` instead of `team.run()`
- `team.aprint_response()` instead of `team.print_response()`

### Supported Protocols

1. **AgentOS Protocol** (default): Agno's native REST API
2. **A2A Protocol**: Agent-to-Agent protocol for cross-framework communication

```python
# A2A protocol example
remote_agent = RemoteAgent(
    base_url="http://a2a-server:8080",
    agent_id="external-agent",
    protocol="a2a",        # Use A2A instead of AgentOS
    a2a_protocol="rest",   # "rest" or "json-rpc"
)
```

## Examples

| File | Description |
|------|-------------|
| `01_basic_remote_member.py` | Basic setup with local + remote agents |
| `02_a2a_protocol.py` | Using A2A protocol for cross-framework agents |
| `03_multi_server_team.py` | Distributed team across multiple servers |

## Running the Examples

1. **Start a remote AgentOS server:**
   ```bash
   # On the remote machine
   python -m agno.os --agents path/to/agents.py --port 7777
   ```

2. **Update the cookbook with your server URL:**
   ```python
   remote_agent = RemoteAgent(
       base_url="http://your-server:7777",
       agent_id="your-agent-id",
   )
   ```

3. **Run the cookbook:**
   ```bash
   python cookbook/03_teams/23_remote_agents/01_basic_remote_member.py
   ```

## Architecture

```
┌─────────────────┐     HTTP/REST      ┌─────────────────┐
│   Local Team    │ ←───────────────── │  Remote Server  │
│                 │                     │                 │
│  ┌───────────┐  │                     │  ┌───────────┐  │
│  │ Leader    │  │   delegate_task     │  │ Explorer  │  │
│  └───────────┘  │ ─────────────────→  │  └───────────┘  │
│        │        │                     │        │        │
│  ┌───────────┐  │                     │  Runs locally   │
│  │ Summarizer│  │                     │  on server      │
│  │ (local)   │  │                     │                 │
│  └───────────┘  │                     └─────────────────┘
│        │        │
│  ┌───────────┐  │
│  │RemoteAgent│──┼── Proxy to remote
│  │ (proxy)   │  │
│  └───────────┘  │
└─────────────────┘
```

## Use Cases

- **Specialized Hardware**: ML agents on GPU servers, RAG agents on high-memory machines
- **Geographic Distribution**: Agents closer to data sources
- **Security Isolation**: Sensitive agents on private networks
- **Microservices**: Each agent as an independent service
