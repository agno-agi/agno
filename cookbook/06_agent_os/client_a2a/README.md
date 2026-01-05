# A2AClient Cookbook Examples

This directory contains examples demonstrating how to use `A2AClient` to communicate with A2A-compatible agent servers.

## What is A2A?

A2A (Agent-to-Agent) is a standardized protocol for agent-to-agent communication, enabling interoperability between different AI agent frameworks.

## Prerequisites

### Client Only
```bash
pip install agno httpx
```

### Running AgentOS Server
```bash
pip install "agno[os]"
```

### Running Google ADK Server
```bash
pip install google-adk a2a-sdk uvicorn
export GOOGLE_API_KEY=your_api_key_here
```

## Examples

### Agno AgentOS Examples (localhost:7003)

| File | Description |
|------|-------------|
| `01_basic_messaging.py` | Simple send/receive with A2AClient |
| `02_streaming.py` | Real-time streaming responses |
| `03_multi_turn.py` | Multi-turn conversations with context |
| `04_error_handling.py` | Handling errors and edge cases |
| `servers/agno_server.py` | Agno AgentOS A2A server |

### Google ADK Examples (localhost:8001)

| File | Description |
|------|-------------|
| `05_connect_to_google_adk.py` | Connect to Google ADK A2A server |
| `06_multi_turn_with_google_adk.py` | Multi-turn conversations with ADK |
| `07_remote_agent_a2a.py` | **RemoteAgent with A2A protocol** |
| `servers/google_adk_server.py` | Google ADK A2A server |

## Quick Start

```python
from agno.client.a2a import A2AClient

client = A2AClient("http://localhost:7003/a2a/agents/basic-agent")
result = await client.send_message(
    message="Hello!"
)
print(result.content)
```

## A2AClient vs AgentOSClient

| Feature | A2AClient | AgentOSClient |
|---------|-----------|---------------|
| Protocol | A2A standard (JSON-RPC) | Agno REST API |
| Compatible with | Any A2A server | Agno servers only |
| Features | Messaging only | Full platform features |
| Use case | Cross-framework communication | Full Agno integration |

## API Reference

### A2AClient

```python
A2AClient(
    base_url: str,                              # Server URL (include agent path)
    timeout: int = 30,                          # Request timeout in seconds
    protocol: Literal["rest", "json-rpc"] = "rest"  # Protocol mode
)
```

### Methods

- `send_message(message, ...)` - Send message and wait for response
- `stream_message(message, ...)` - Stream message with real-time events
- `get_agent_card()` - Get agent capability card (if supported)

### Response Types

- `TaskResult` - Non-streaming response with `content`, `status`, `artifacts`
- `StreamEvent` - Streaming event with `event_type`, `content`, `is_final`

## Running Examples

### With Agno AgentOS Server

```bash
# Start the Agno A2A server first
python cookbook/06_agent_os/client_a2a/servers/agno_server.py

# In another terminal, run examples
python cookbook/06_agent_os/client_a2a/01_basic_messaging.py
python cookbook/06_agent_os/client_a2a/02_streaming.py
python cookbook/06_agent_os/client_a2a/03_multi_turn.py
```

### With Google ADK Server

This demonstrates cross-framework A2A communication (Agno client -> Google ADK server).

```bash
# Start the Google ADK server
python cookbook/06_agent_os/client_a2a/servers/google_adk_server.py

# In another terminal, run examples
python cookbook/06_agent_os/client_a2a/05_connect_to_google_adk.py
python cookbook/06_agent_os/client_a2a/07_multi_turn_with_google_adk.py
```

**Key Difference:** Google ADK uses pure JSON-RPC at root "/", so use `protocol="json-rpc"`:

```python
# Google ADK uses pure JSON-RPC mode (all calls POST to root "/")
client = A2AClient("http://localhost:8001/", protocol="json-rpc")
result = await client.send_message(
    message="Hello!"
)
```

## RemoteAgent with A2A Protocol

For a more familiar interface, you can use `RemoteAgent` with `protocol="a2a"`:

```python
from agno.agent import RemoteAgent

# Connect to Google ADK via A2A protocol
agent = RemoteAgent(
    base_url="http://localhost:8001",
    agent_id="facts_agent",
    protocol="a2a",
    a2a_protocol="json-rpc",  # Required for Google ADK
)

# Use the same interface as local agents
result = await agent.arun("Tell me about the moon")
print(result.content)

# Streaming works too
async for event in agent.arun("Tell me a story", stream=True):
    print(event.content, end="")
```

**Protocol Options:**
- `protocol="agentos"` (default): Use Agno specific REST API
- `protocol="a2a"`: Use A2A protocol for cross-framework communication
