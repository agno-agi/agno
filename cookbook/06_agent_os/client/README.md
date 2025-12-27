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
| `06_run_teams.py` | Execute team runs with streaming support |
| `07_run_workflows.py` | Execute workflow runs with sessions |
| `08_run_evals.py` | Run accuracy/performance evaluations |
| `09_upload_content.py` | Upload documents to knowledge base |

## Quick Start

### 1. Start the AgentOS Server

**Prerequisites**: Set your OpenAI API key before starting the server:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

Use the included `server.py` which has all features needed for the examples:

```bash
# From the repository root
python3 cookbook/agent_os/client/server.py

# Or if running from this directory
python server.py
```

The server runs on http://localhost:7777 and includes:
- **Agents**: `assistant` (calculator, memory, knowledge), `researcher` (web search)
- **Teams**: `researchteam` (coordinates both agents)
- **Workflows**: `qaworkflow` (Q&A using assistant)
- **Knowledge**: ChromaDB vector store with contents database

<details>
<summary>Alternative: Create a minimal server inline</summary>

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
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app)  # Runs on http://localhost:7777
```

Note: This minimal setup won't support all cookbook examples (e.g., memory, teams, workflows).
</details>

### 2. Connect with AgentOSClient

```python
import asyncio
from agno.client.os import AgentOSClient

async def main():
    client = AgentOSClient(base_url="http://localhost:7777")

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

### Agent Run Operations

```python
# Non-streaming run
result = await client.run_agent(agent_id="agent-id", message="Hello")

# Streaming run
async for line in client.run_agent_stream(agent_id="agent-id", message="Hello"):
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

### Team Run Operations

```python
# Non-streaming team run
result = await client.run_team(team_id="team-id", message="Hello team")

# Streaming team run
async for line in client.run_team_stream(team_id="team-id", message="Hello"):
    print(line)

# Cancel a team run
await client.cancel_team_run(team_id="team-id", run_id="run-id")
```

### Workflow Run Operations

```python
# Non-streaming workflow run
result = await client.run_workflow(workflow_id="workflow-id", message="Start")

# Streaming workflow run
async for line in client.run_workflow_stream(workflow_id="workflow-id", message="Start"):
    print(line)

# Cancel a workflow run
await client.cancel_workflow_run(workflow_id="workflow-id", run_id="run-id")
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
# Upload content to knowledge base
result = await client.upload_content(file_path="document.pdf", name="My Doc")

# Get content status
status = await client.get_content_status(content_id="content-id")

# List content
content = await client.list_content()

# Search knowledge base
results = await client.search_knowledge(query="What is X?")

# Get knowledge config
config = await client.get_knowledge_config()

# Delete content
await client.delete_content(content_id="content-id")
```

### Eval Operations

```python
from agno.db.schemas.evals import EvalType

# Run accuracy evaluation
eval_result = await client.run_eval(
    agent_id="agent-id",
    eval_type=EvalType.ACCURACY,
    input_text="What is 2+2?",
    expected_output="4",
)

# Run performance evaluation
eval_result = await client.run_eval(
    agent_id="agent-id",
    eval_type=EvalType.PERFORMANCE,
    input_text="Hello",
    num_iterations=3,
)

# List evaluation runs
evals = await client.list_eval_runs()

# Get evaluation details
eval_run = await client.get_eval_run(eval_id="eval-id")
```

## Authentication

If your AgentOS server requires authentication, pass headers to each request:

```python
headers = {"Authorization": "Bearer your-token"}

# Pass headers to any request
config = await client.get_config(headers=headers)
result = await client.run_agent(agent_id="agent-id", message="Hello", headers=headers)
```

## Usage

```python
# Create client instance
client = AgentOSClient(base_url="http://localhost:7777")

# Make requests directly
result = await client.run_agent(agent_id="agent-id", message="Hello")
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

