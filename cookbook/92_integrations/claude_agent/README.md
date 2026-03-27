# Claude Agent SDK Integration

Run Claude Agent SDK agents as first-class citizens in Agno and AgentOS.

## What is ClaudeAgent?

`ClaudeAgent` wraps the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) so it can be used:

- **Standalone** — call `arun()` directly, just like a native Agno agent
- **With AgentOS** — register it alongside native Agno agents and access via the REST API

## Setup

```bash
pip install claude-agent-sdk agno
export ANTHROPIC_API_KEY=sk-...
```

## Examples

| File | Description |
|------|-------------|
| `basic.py` | Standalone usage with streaming and non-streaming |
| `agent_os.py` | Running alongside native Agno agents in AgentOS |

## Quick Start

```python
from agno.agent.claude import ClaudeAgent

agent = ClaudeAgent(
    agent_id="my-agent",
    name="My Agent",
    system_prompt="You are a helpful assistant.",
    allowed_tools=["Read", "Glob", "Grep"],
)

# Non-streaming
response = await agent.arun("What files are here?")
print(response.content)

# Streaming
async for event in agent.arun("Find Python files", stream=True):
    if event.event == "RunContent":
        print(event.content, end="")
```

## With AgentOS

```python
from agno.agent.claude import ClaudeAgent
from agno.os import AgentOS

agent = ClaudeAgent(
    agent_id="code-assistant",
    name="Code Assistant",
    allowed_tools=["Read", "Glob", "Grep", "Bash"],
)

app = AgentOS(agents=[agent]).get_app()
```

Then access via the standard AgentOS API:

```bash
curl -X POST http://localhost:7777/agents/code-assistant/runs \
  -F "message=Review auth.py" \
  -F "stream=false"
```
