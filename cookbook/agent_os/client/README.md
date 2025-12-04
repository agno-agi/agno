# AgentOSClient Cookbook

The `AgentOSClient` provides programmatic access to AgentOS API endpoints, allowing you to interact with remote AgentOS instances from any Python application.

## Examples

| File | Description |
|------|-------------|
| `01_basic_client.py` | Connect to AgentOS and discover available agents, teams, workflows |
| `02_run_agents.py` | Execute agent runs with streaming and non-streaming responses |
| `03_memory_operations.py` | Create, read, update, delete user memories |
| `04_session_management.py` | Manage sessions and conversation history |
| `05_knowledge_search.py` | Search the knowledge base |

## Quick Start

### 1. Start an AgentOS Server

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful assistant.",
)

agent_os = AgentOS(agents=[agent])
agent_os.serve()  # Runs on http://localhost:7777
```

### 2. Connect with AgentOSClient

```python
import asyncio
from agno.os.client import AgentOSClient

async def main():
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        # Discover available agents
        config = await client.get_config()
        print(f"Agents: {[a.id for a in config.agents]}")
        
        # Run an agent
        result = await client.run_agent(
            agent_id="assistant",
            message="Hello!",
        )
        print(f"Response: {result.content}")

asyncio.run(main())
```

## API Reference

### Discovery Operations

```python
# Get AgentOS configuration
config = await client.get_config()

# Get specific agent/team/workflow details
agent = await client.get_agent("agent-id")
team = await client.get_team("team-id")
workflow = await client.get_workflow("workflow-id")
```

### Run Operations

```python
# Non-streaming run
result = await client.run_agent(agent_id="agent-id", message="Hello")

# Streaming run
async for line in client.stream_agent_run(agent_id="agent-id", message="Hello"):
    print(line)

# Run with session context
result = await client.run_agent(
    agent_id="agent-id",
    message="Hello",
    session_id="session-id",
    user_id="user-id",
)

# Cancel a run
await client.cancel_agent_run(agent_id="agent-id", run_id="run-id")
```

### Session Operations

```python
# Create session
session = await client.create_session(agent_id="agent-id", user_id="user-id")

# List sessions
sessions = await client.list_sessions(user_id="user-id")

# Get session details
session = await client.get_session(session_id="session-id")

# Get runs in a session
runs = await client.get_session_runs(session_id="session-id")

# Delete session
await client.delete_session(session_id="session-id")
```

### Memory Operations

```python
# Create memory
memory = await client.create_memory(
    memory="User likes blue",
    user_id="user-id",
    topics=["preferences"],
)

# List memories
memories = await client.list_memories(user_id="user-id")

# Update memory
await client.update_memory(memory_id="mem-id", memory="Updated", user_id="user-id")

# Delete memory
await client.delete_memory(memory_id="mem-id", user_id="user-id")
```

### Knowledge Operations

```python
# Search knowledge base
results = await client.search_knowledge(query="What is X?")

# Get knowledge config
config = await client.get_knowledge_config()

# List content
content = await client.list_content()
```

## Authentication

If your AgentOS server requires authentication, provide an API key:

```python
client = AgentOSClient(
    base_url="http://localhost:7777",
    api_key="your-api-key",  # Or set AGNO_API_KEY environment variable
)
```

## Connection Management

### Using Context Manager (Recommended)

```python
async with AgentOSClient(base_url="http://localhost:7777") as client:
    # Client is automatically connected and cleaned up
    result = await client.run_agent(...)
```

### Manual Connection

```python
client = AgentOSClient(base_url="http://localhost:7777")
await client.connect()
try:
    result = await client.run_agent(...)
finally:
    await client.close()
```

## Error Handling

The client raises `httpx.HTTPStatusError` for HTTP errors:

```python
from httpx import HTTPStatusError

try:
    result = await client.run_agent(agent_id="nonexistent", message="Hello")
except HTTPStatusError as e:
    print(f"HTTP {e.response.status_code}: {e.response.text}")
```

