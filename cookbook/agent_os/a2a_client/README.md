# A2AClient Cookbook Examples

This directory contains examples demonstrating how to use `A2AClient` to communicate with A2A-compatible agent servers.

## What is A2A?

A2A (Agent-to-Agent) is a standardized protocol for agent-to-agent communication, enabling interoperability between different AI agent frameworks.

## Prerequisites

1. Install agno with httpx:
   ```bash
   pip install agno httpx
   ```

2. Start an AgentOS server with A2A interface:
   ```bash
   python cookbook/agent_os/interfaces/a2a/basic.py
   ```

## Examples

### Agno AgentOS Examples (localhost:7777)

| File | Description |
|------|-------------|
| `01_basic_messaging.py` | Simple send/receive with A2AClient |
| `02_streaming.py` | Real-time streaming responses |
| `03_multi_turn.py` | Multi-turn conversations with context |
| `04_error_handling.py` | Handling errors and edge cases |

### Google ADK Examples (localhost:8001)

| File | Description |
|------|-------------|
| `05_connect_to_google_adk.py` | Connect to Google ADK A2A server |
| `06_streaming_with_google_adk.py` | Streaming with Google ADK |
| `07_multi_turn_with_google_adk.py` | Multi-turn conversations with ADK |
| `servers/google_adk_server.py` | Google ADK A2A server |

## Quick Start

```python
from agno.a2a import A2AClient

async with A2AClient("http://localhost:7777") as client:
    result = await client.send_message(
        agent_id="basic-agent",
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
    base_url: str,           # Server URL
    timeout: float = 300.0,  # Request timeout
    a2a_prefix: str = "/a2a" # A2A endpoint prefix
)
```

### Methods

- `send_message(agent_id, message, ...)` - Send message and wait for response
- `stream_message(agent_id, message, ...)` - Stream message with real-time events
- `get_agent_card()` - Get agent capability card (if supported)

### Response Types

- `TaskResult` - Non-streaming response with `content`, `status`, `artifacts`
- `StreamEvent` - Streaming event with `event_type`, `content`, `is_final`

## Running Examples

### With Agno AgentOS Server

```bash
# Start the Agno A2A server first
python cookbook/agent_os/interfaces/a2a/basic.py

# In another terminal, run examples
python cookbook/agent_os/a2a_client/01_basic_messaging.py
python cookbook/agent_os/a2a_client/02_streaming.py
python cookbook/agent_os/a2a_client/03_multi_turn.py
```

### With Google ADK Server

This demonstrates cross-framework A2A communication (Agno client -> Google ADK server).

**Prerequisites:**

1. Install Google ADK:
   ```bash
   pip install google-adk uvicorn
   ```

2. Set your Google API key:
   ```bash
   export GOOGLE_API_KEY=your_api_key_here
   ```

3. Start the Google ADK server:
   ```bash
   python cookbook/agent_os/a2a_client/servers/google_adk_server.py
   ```

4. Run the examples:
   ```bash
   python cookbook/agent_os/a2a_client/05_connect_to_google_adk.py
   python cookbook/agent_os/a2a_client/07_multi_turn_with_google_adk.py
   ```

**Key Difference:** Google ADK uses pure JSON-RPC at root "/", so use `json_rpc_endpoint="/"`:

```python
# Google ADK uses pure JSON-RPC mode (all calls POST to root "/")
async with A2AClient("http://localhost:8001", json_rpc_endpoint="/") as client:
    result = await client.send_message(
        agent_id="facts_agent",
        message="Hello!"
    )
```

