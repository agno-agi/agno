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

## Running the Example

1. **Start a remote AgentOS server:**
   ```bash
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

## Code Path

When a Team delegates to a RemoteAgent member:

```
team.arun()
    │
    ▼
_run.py:2127 ─────────────────────────────────────────────────────────
    │   _tools = _determine_tools_for_model(..., async_mode=True, ...)
    │   # async_mode=True because we're in arun()
    ▼
_tools.py:306 ────────────────────────────────────────────────────────
    │   delegate_task_func = _get_delegate_task_function(..., async_mode=True)
    │   # Builds the async delegation tool
    ▼
_default_tools.py:773 ───────────────────────────────────────────────
    │   async def adelegate_task_to_member(member_id, task):
    │       ...
    │       member_agent_run_response = await member_agent.arun(...)  # line 873
    │   # Calls .arun() on member - works for both Agent and RemoteAgent
    ▼
remote.py:259 ────────────────────────────────────────────────────────
    │   def arun(self, input, ...):
    │       # Makes HTTP request to remote AgentOS server
    │       return self.agentos_client.run_agent(...)  # line 329
    ▼
HTTP POST to remote server
```

The key insight: Team uses **duck typing** — it calls `member_agent.arun()` without checking if the member is a local `Agent` or `RemoteAgent`. Both implement the same interface.
