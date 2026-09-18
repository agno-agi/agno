# Agent Protocol Interface

This cookbook demonstrates how to expose Agno agents via the [Agent Protocol](https://github.com/langchain-ai/agent-protocol) -- a framework-agnostic standard for serving LLM agents. Once exposed, any Agent Protocol client (including LangChain's `deepagents` package and the Agno `AgentProtocolClient`) can interact with your Agno agents.

## Examples

| File | Description |
|------|-------------|
| `server.py` | AgentOS server with Agent Protocol interface |
| `client_example.py` | Agno `AgentProtocolClient` connecting to an AgentOS server |
| `async_subagent_example.py` | End-to-end: deepagents AsyncSubAgent connecting to AgentOS |

## Prerequisites

### Install `ap_client` (Agent Protocol Python SDK)

The `ap_client` package is not on PyPI. Install directly from GitHub:

```bash
pip install "git+https://github.com/langchain-ai/agent-protocol.git#subdirectory=client-python"
```

### Run the server

```bash
pip install agno
export ANTHROPIC_API_KEY=your_key_here
python server.py
```

The server starts on `http://localhost:7778` with the Agent Protocol interface at `/ap`.

### Run the Agno client example

```bash
python client_example.py
```

### Run the deepagents example

```bash
pip install deepagents
export ANTHROPIC_API_KEY=your_key_here
python async_subagent_example.py
```

## How It Works

1. The `AgentProtocol` interface exposes Agno agents via standard endpoints:
   - `POST /ap/threads` - Create conversation threads
   - `POST /ap/threads/{id}/runs` - Execute agent runs
   - `GET /ap/threads/{id}/runs/{run_id}` - Check run status
   - `POST /ap/agents/search` - List available agents
   - `POST /ap/runs/wait` - Stateless run (wait for result)
   - `POST /ap/runs/stream` - Stateless run (streaming)
   - And more (store, thread CRUD, etc.)

2. The `AgentProtocolClient` wraps the `ap_client` SDK (sync) and httpx (async) for Agno-native consumption of any Agent Protocol server.

3. The `deepagents` package uses the LangGraph SDK to communicate with these endpoints, enabling async subagent delegation.

## Architecture

```
AgentOS (server.py)                     Clients
+---------------------------+
| Agent Protocol Interface  |  HTTP    AgentProtocolClient (client_example.py)
| /ap/threads              <----------  client.acreate_run_wait(...)
| /ap/threads/{id}/runs    |
| /ap/agents/search        |  HTTP    deepagents (async_subagent_example.py)
| /ap/runs/wait            <----------  AsyncSubAgent(url="...", graph_id="...")
| /ap/store/items          |
+---------------------------+
| Agno Agent               |
| (research_agent)         |
+---------------------------+
```
