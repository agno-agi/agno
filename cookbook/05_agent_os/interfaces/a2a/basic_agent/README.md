# Basic A2A Server + Client

The smallest complete A2A 1.0 pair built on Agno's abstractions:

- `server.py` — exposes an Agno agent over A2A with `AgentOS(a2a_interface=True)`. No protocol code.
- `client.py` — calls it with `A2AClient`, the toolkit that wraps the official `a2a-sdk` client (one instance per remote agent).

## Run it

```bash
# Terminal 1
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/basic_agent/server.py

# Terminal 2
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/basic_agent/client.py
```

Expected output: the agent's v1 AgentCard (JSON) followed by a one-sentence
introduction from the agent.

The server is a standard A2A 1.0 endpoint — it also works with any external
a2a-sdk client, the a2a-inspector, or another framework's A2A client. See the
parent folder's README for the full endpoint reference and stream event shapes.

## Prerequisites

- `a2a-sdk>=1.0` (`pip install -U "a2a-sdk>=1.0"`, already in `agno[a2a]`)
- `OPENAI_API_KEY`
