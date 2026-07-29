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

## Code Path (How It Works)

When a Team delegates to a RemoteAgent member, the execution flows through these steps:

### Step 1: Team.arun() sets async_mode=True

**File:** `libs/agno/agno/team/_run.py:2119-2127`

```python
_tools = _determine_tools_for_model(
    team,
    model=team.model,
    run_response=run_response,
    run_context=run_context,
    ...
    async_mode=True,  # <-- Set because we're in arun()
    ...
)
```

The `async_mode=True` flag propagates through the tool-building chain.

### Step 2: Tool builder passes async_mode to delegate function factory

**File:** `libs/agno/agno/team/_tools.py:296-306`

```python
delegate_task_func = _get_delegate_task_function(
    team,
    run_response=run_response,
    run_context=run_context,
    session=session,
    ...
    async_mode=async_mode,  # <-- Passed through
    ...
)
```

### Step 3: Factory returns async or sync delegate function based on async_mode

**File:** `libs/agno/agno/team/_default_tools.py:1414-1417`

```python
if async_mode:
    delegate_function = adelegate_task_to_member  # <-- Async version
else:
    delegate_function = delegate_task_to_member   # <-- Sync version

delegate_func = Function.from_callable(delegate_function, name="delegate_task_to_member")
```

### Step 4: Async delegate function calls member_agent.arun()

**File:** `libs/agno/agno/team/_default_tools.py:812-834` (streaming) and `:873` (non-streaming)

```python
async def adelegate_task_to_member(member_id: str, task: str):
    ...
    # Find the member (could be Agent or RemoteAgent)
    _, member_agent = result
    
    if stream:
        member_agent_run_response_stream = member_agent.arun(  # <-- Duck typing!
            input=member_agent_task,
            ...
            stream=True,
        )
        async for event in member_agent_run_response_stream:
            yield event
    else:
        member_agent_run_response = await member_agent.arun(  # <-- Duck typing!
            input=member_agent_task,
            ...
            stream=False,
        )
```

**Key insight:** The code calls `member_agent.arun()` without checking the type. Both `Agent` and `RemoteAgent` implement `arun()`, so duck typing works.

### Step 5: RemoteAgent.arun() makes HTTP request to remote server

**File:** `libs/agno/agno/agent/remote.py:259-351`

```python
def arun(self, input, *, stream=None, ...):
    validated_input = validate_input(input)
    serialized_input = serialize_input(validated_input)
    headers = self._get_auth_headers(auth_token)

    # AgentOS protocol path (default)
    if self.agentos_client:
        if stream:
            return self.agentos_client.run_agent_stream(
                agent_id=self.agent_id,
                message=serialized_input,
                session_id=session_id,
                ...
            )
        else:
            return self.agentos_client.run_agent(
                agent_id=self.agent_id,
                message=serialized_input,
                session_id=session_id,
                ...
            )
```

The `agentos_client.run_agent()` makes an HTTP POST to the remote server's `/v1/agents/{agent_id}/runs` endpoint.

## Why RemoteAgent Works as Team Member

1. **Duck typing:** Team doesn't check `isinstance(member, RemoteAgent)` — it just calls `.arun()`
2. **Same interface:** Both `Agent` and `RemoteAgent` implement `arun()` with compatible signatures
3. **Async propagation:** `async_mode=True` flows from `team.arun()` through the tool chain
4. **HTTP abstraction:** `RemoteAgent.arun()` wraps HTTP calls to look like local execution

## Constraint: Async Only

`RemoteAgent` does NOT implement `run()` (sync). If you try to use `team.run()` with a RemoteAgent member:

1. `_run.py` sets `async_mode=False`
2. `_default_tools.py` returns `delegate_task_to_member` (sync version)
3. Sync delegate calls `member_agent.run()` 
4. `RemoteAgent` has no `run()` method → **AttributeError**

Always use `team.arun()` or `team.aprint_response()` with RemoteAgent members.
