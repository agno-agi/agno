# Frameworks Quickstart: Agno, Claude Code, LangGraph, DSPy

AgentOS supports agents built with **Agno**, the **Claude Agent SDK** (Claude Code), **LangGraph**, and **DSPy** — served through one runtime, one API, and one UI.

This quickstart shows each framework on its own and all together.

## What's Here

| File | What It Shows |
|:-----|:--------------|
| `agno_agent.py` | Native Agno agent with the `Workspace` tool (read/edit/search/shell, with confirmation gates) |
| `claude_agent.py` | Claude Code agent via the Claude Agent SDK, with `Read`, `Edit`, `Bash` tools |
| `langgraph_agent.py` | A LangGraph chatbot wrapped for AgentOS |
| `dspy_agent.py` | A DSPy `ChainOfThought` program wrapped for AgentOS |
| `multi_framework_agentos.py` | Agno + Claude Code in one AgentOS — the example from the launch blog post |

Each example uses SQLite for session storage so you can run it with no infra setup.

## The Multi-Framework Example

```python
from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace

# Claude Code agent
claude_agent = ClaudeAgent(
    name="Claude Code Agent",
    model="claude-sonnet-4-6",
    allowed_tools=["Read", "Edit", "Bash"],
    permission_mode="acceptEdits",
    max_turns=10,
)

# Agno agent
agno_agent = Agent(
    name="Agno Agent",
    model="openai:gpt-5.4",
    tools=[
        Workspace(
            root=".",
            allowed=["read", "list", "search"],
            confirm=["write", "edit", "delete", "shell"],
        )
    ],
)

agent_os = AgentOS(
    agents=[agno_agent, claude_agent],
    tracing=True,
    db=SqliteDb(db_file="tmp/agentos.db"),
)
app = agent_os.get_app()
```

Both agents share session storage, the API surface and the AgentOS UI.

## Run It

Install the dependencies for the framework(s) you want:

```bash
# Claude Agent SDK
pip install claude-agent-sdk

# LangGraph
pip install langgraph langchain-openai

# DSPy
pip install dspy
```

Set your API keys:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

Run any of the examples:

```bash
python cookbook/frameworks/00_quickstart/multi_framework_agentos.py
```

The AgentOS UI is at <http://localhost:7777>. To list agents over HTTP:

```bash
curl http://localhost:7777/agents
```

To run an agent:

```bash
curl -X POST http://localhost:7777/agents/agno-agent/runs \
    -F "message=List the Python files in this directory" \
    -F "stream=true" --no-buffer
```

## Where to Go Next

- `../claude-agent-sdk/` — sessions, custom MCP tools, and more Claude SDK patterns
- `../langgraph/` — tool calls, sessions, time travel
- `../dspy/` — sessions, ReAct with tools
- [AgentOS docs](https://docs.agno.com/agent-os/introduction)

## Status

Claude Agent SDK, LangGraph, and DSPy support is in early alpha. Not every feature is wired up yet — please file issues for rough edges.
