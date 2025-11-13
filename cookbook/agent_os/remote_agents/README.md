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

Call an agent hosted on a remote AgentOS instance:

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
- `01_standalone_runner.py` to run a standalone `AgentOSRunner` example. This is the most basic example that interfaces with the AgentOS instance.
- `02_agent_os_gateway.py` to run an `AgentOS` that interfaces with your "remote" agent, team and workflow via the `AgentOSRunner`.