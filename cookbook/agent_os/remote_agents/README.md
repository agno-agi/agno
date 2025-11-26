# Remote Agents

Tools for interacting with remote AgentOS instances via HTTP.

## Overview

This package provides two complementary tools for remote agent operations:

### `AgentOSRunner` - Execution Client
Focused on **running** agents, teams, and workflows remotely. Use when you only need execution capabilities.

### `AgentOSClient` - Full-Featured Client
Comprehensive client for **discovery, management, and execution**. Use when you need to:
- Discover available agents, teams, and workflows
- Get detailed configuration information
- List models in use
- Execute agents/teams/workflows

Both enable:
- **Microservices architecture**: Call agents running on different servers
- **Load distribution**: Distribute agent workloads across multiple instances
- **Hybrid deployments**: Mix local and remote agents in the same application
- **Consistent API**: Same interface for local and remote execution

## When to Use Which?

| Need | Use |
|------|-----|
| Just execute remote agents | `AgentOSRunner` |
| Discover what's available | `AgentOSClient` |
| Get agent configurations | `AgentOSClient` |
| List models/tools | `AgentOSClient` |
| Full API access | `AgentOSClient` |
| Minimal dependencies | `AgentOSRunner` |

## Installation

Both `AgentOSRunner` and `AgentOSClient` are included with the Agno framework. For remote execution, ensure you have `httpx` installed:

```bash
pip install httpx
```

---

## AgentOSClient Usage

Full-featured client for discovery, management, and execution.

### Discovery Example

```python
from agno.os import AgentOSClient

async with AgentOSClient(base_url="http://localhost:7777") as client:
    # Discover available resources
    agents = await client.list_agents()
    teams = await client.list_teams()
    workflows = await client.list_workflows()

    print(f"Found {len(agents)} agents, {len(teams)} teams, {len(workflows)} workflows")

    # Get detailed configuration
    agent_config = await client.get_agent("my-agent")
    print(f"Agent model: {agent_config.model}")
```

### Execution via Client

```python
from agno.os import AgentOSClient

async with AgentOSClient(base_url="http://localhost:7777") as client:
    # Method 1: Get a runner and execute (recommended for multiple runs)
    runner = client.agent("my-agent")
    response = await runner.arun("What is 2+2?")

    # Method 2: Direct execution (convenience)
    response = await client.run_agent("my-agent", "What is 2+2?")
```

### Configuration Inspection

```python
from agno.os import AgentOSClient

async with AgentOSClient(base_url="http://localhost:7777") as client:
    # Get OS configuration
    config = await client.get_config()
    print(f"OS: {config.os_id}")

    # List models
    models = await client.get_models()
    for model in models:
        print(f"Model: {model.id} ({model.provider})")
```

---

## AgentOSRunner Usage

Focused client for execution-only operations. Call an agent hosted on a remote AgentOS instance:

```python
from agno.runner import AgentOSRunner

# Create a remote agent runner
runner = AgentOSRunner(
    base_url="http://localhost:7777",
    agent_id="my-agent",
    api_key="optional-api-key",  # Optional authentication if your remote agent is using a different API key than the default AGNO_API_KEY
    timeout=300.0,  # Request timeout in seconds
)

# Run the remote agent (same interface!)
response = await runner.arun("What is 2+2?")
print(response.content)
```

**Note:** You must provide exactly one of agent_id, team_id, or workflow_id.
**Note:** Streaming is supported by setting `stream=True` when calling `arun()`.

## API Reference

### Constructor Parameters

- `base_url` (str): Base URL of the remote AgentOS instance (e.g., "http://localhost:7777")
- `agent_id` (Optional[str]): ID of the remote agent
- `team_id` (Optional[str]): ID of the remote team
- `workflow_id` (Optional[str]): ID of the remote workflow
- `api_key` (Optional[str]): API key for authentication
- `timeout` (float): Request timeout in seconds (default: 300)

### Remote Agents

```python
runner = AgentOSRunner(
    base_url="http://localhost:7777",
    agent_id="my-agent",
)

response = await runner.arun("What is 2+2?")
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

## Architecture

### Remote API Endpoints

The runner calls these AgentOS API endpoints:

- **Agents**: `POST /v1/agents/{agent_id}/run`
- **Teams**: `POST /v1/teams/{team_id}/run`
- **Workflows**: `POST /v1/workflows/{workflow_id}/run`

### Request/Response Flow

 - Serializes the input and parameters
 - Makes an HTTP POST request to the AgentOS API
 - Handles streaming via Server-Sent Events (SSE)
 - Deserializes the response into `RunOutput`


## Examples

### Setup:

Run the `agent_os_setup.py` script to setup the AgentOS instance. This starts an AgentOS instance with a basic agent, team and workflow. This plays the part of the "Remote AgentOS" in the examples below.
Do this in one terminal instance.

In another terminal instance, run:
- `01_standalone_runner.py` - Basic `AgentOSRunner` example for execution-only operations
- `02_agent_os_gateway.py` - `AgentOS` acting as gateway to remote agents via `AgentOSRunner`
- `03_agent_os_client.py` - `AgentOSClient` demonstrating discovery, configuration, and execution

### Example Outputs

**01_standalone_runner.py**: Shows direct agent execution via runner
**02_agent_os_gateway.py**: Shows AgentOS as a gateway/proxy pattern
**03_agent_os_client.py**: Shows comprehensive client usage including:
- Discovering available agents/teams/workflows
- Getting detailed configurations
- Listing models in use
- Executing via client (multiple patterns)
- Error handling