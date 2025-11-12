# AgentOSRunner

A unified client for running agents, teams, and workflows both locally and remotely via HTTP.

## Overview

`AgentOSRunner` provides a consistent interface for executing agents regardless of whether they're running locally or hosted on a remote AgentOS instance. This enables:

- **Microservices architecture**: Call agents running on different servers
- **Load distribution**: Distribute agent workloads across multiple instances
- **Hybrid deployments**: Mix local and remote agents in the same application
- **Consistent API**: Same interface for local and remote execution

## Installation

The `AgentOSRunner` is included with the Agno framework. For remote execution, ensure you have `httpx` installed:

```bash
pip install httpx
```

## Usage

### Local Execution

Run an agent locally by providing the agent instance:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.runner import AgentOSRunner

# Create a local agent
agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful assistant",
)

# Wrap in runner
runner = AgentOSRunner(agent=agent)

# Run the agent
response = await runner.arun("What is 2+2?")
print(response.content)
```

### Remote Execution

Call an agent hosted on a remote AgentOS instance:

```python
from agno.runner import AgentOSRunner

# Create a remote agent runner
runner = AgentOSRunner(
    base_url="http://localhost:7777",
    agent_id="my-agent",
    api_key="optional-api-key",  # Optional authentication
    timeout=300.0,  # Request timeout in seconds
)

# Run the remote agent (same interface!)
response = await runner.arun("What is 2+2?")
print(response.content)
```

## API Reference

### Constructor Parameters

#### For Local Execution:
- `agent` (Optional[Agent]): Local agent instance
- `team` (Optional[Team]): Local team instance  
- `workflow` (Optional[Workflow]): Local workflow instance

#### For Remote Execution:
- `base_url` (str): Base URL of the remote AgentOS instance (e.g., "http://localhost:7777")
- `agent_id` (Optional[str]): ID of the remote agent
- `team_id` (Optional[str]): ID of the remote team
- `workflow_id` (Optional[str]): ID of the remote workflow
- `api_key` (Optional[str]): API key for authentication
- `timeout` (float): Request timeout in seconds (default: 300)

**Note:** You must provide either local OR remote configuration, not both.

### Methods

#### `arun()`

Execute the agent/team/workflow asynchronously. The interface matches `Agent.arun()`:

```python
async def arun(
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
    *,
    stream: Optional[bool] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream_events: Optional[bool] = None,
    stream_intermediate_steps: Optional[bool] = None,
    retries: Optional[int] = None,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> Union[RunOutput, AsyncIterator[Union[RunOutputEvent, RunOutput]]]:
```

## Examples

### Streaming Responses

```python
# Works the same for local and remote
runner = AgentOSRunner(base_url="http://localhost:7777", agent_id="my-agent")

async for chunk in runner.arun("Tell me a story", stream=True):
    if hasattr(chunk, 'content') and chunk.content:
        print(chunk.content, end="", flush=True)
```

### Conversation History

```python
runner = AgentOSRunner(base_url="http://localhost:7777", agent_id="my-agent")

# First message
await runner.arun(
    "My name is Alice",
    user_id="alice",
    session_id="conv-1",
    add_history_to_context=True,
)

# Agent remembers previous context
response = await runner.arun(
    "What's my name?",
    user_id="alice",
    session_id="conv-1",
    add_history_to_context=True,
)
```

### Remote Teams

```python
runner = AgentOSRunner(
    base_url="http://localhost:7777",
    team_id="research-team",
)

response = await runner.arun("Research AI trends in 2024")
```

### Remote Workflows

```python
runner = AgentOSRunner(
    base_url="http://localhost:7777",
    workflow_id="data-pipeline",
)

response = await runner.arun(
    "Process data",
    session_state={"data": [1, 2, 3, 4, 5]},
)
```

## Error Handling

```python
import httpx
from agno.runner import AgentOSRunner

runner = AgentOSRunner(
    base_url="http://localhost:7777",
    agent_id="my-agent",
    timeout=30.0,
)

try:
    response = await runner.arun("Hello")
except httpx.HTTPError as e:
    print(f"HTTP Error: {e}")
except httpx.TimeoutException:
    print("Request timed out")
except Exception as e:
    print(f"Error: {e}")
```

## Architecture

### Remote API Endpoints

The runner calls these AgentOS API endpoints:

- **Agents**: `POST /v1/agents/{agent_id}/run`
- **Teams**: `POST /v1/teams/{team_id}/run`
- **Workflows**: `POST /v1/workflows/{workflow_id}/run`

### Request/Response Flow

1. **Local Mode**: Directly calls the agent/team/workflow's `arun()` method
2. **Remote Mode**: 
   - Serializes the input and parameters
   - Makes an HTTP POST request to the AgentOS API
   - Handles streaming via Server-Sent Events (SSE)
   - Deserializes the response into `RunOutput`

## Best Practices

1. **Reuse runners**: Create the runner once and reuse it for multiple calls
   ```python
   runner = AgentOSRunner(base_url="...", agent_id="...")
   for query in queries:
       await runner.arun(query)  # Reuse the runner
   ```

2. **Set appropriate timeouts**: Long-running agents may need higher timeouts
   ```python
   runner = AgentOSRunner(base_url="...", agent_id="...", timeout=600.0)
   ```

3. **Handle errors gracefully**: Network issues can occur with remote calls
   ```python
   try:
       response = await runner.arun(query)
   except Exception as e:
       # Fallback logic
   ```

4. **Use authentication**: Protect your AgentOS endpoints
   ```python
   runner = AgentOSRunner(
       base_url="https://agents.example.com",
       agent_id="...",
       api_key=os.getenv("AGENT_API_KEY"),
   )
   ```

## See Also

- [Agent Documentation](https://docs.agno.com/agents)
- [AgentOS Documentation](https://docs.agno.com/agent-os)
- [Examples](../../cookbook/agent_os/runner_examples.py)

