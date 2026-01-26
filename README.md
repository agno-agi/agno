<div align="center" id="top">
  <a href="https://agno.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg">
      <img src="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg" alt="Agno">
    </picture>
  </a>
</div>

<p align="center">
  Build, run, manage multi-agent systems.
</p>

<div align="center">
  <a href="https://docs.agno.com">Docs</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://community.agno.com/">Community</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://www.agno.com/discord">Discord</a>
</div>

## What is Agno?

Agno is a framework, runtime, and control plane for multi-agent systems.

| Layer | What it does |
|-------|--------------|
| **Framework** | Build agents, teams, and workflows with memory, knowledge, guardrails, and 100+ integrations |
| **AgentOS Runtime** | Run your system in production with a stateless, secure FastAPI backend |
| **Control Plane** | Test, monitor, and manage your system using the [AgentOS UI](https://os.agno.com) |

## Why Agno?

- **Private by design.** AgentOS runs in your cloud. The control plane connects directly to your runtime from your browser. No retention costs, no vendor lock-in, no compliance headaches.
- **Production-ready on day one.** Pre-built FastAPI runtime with SSE endpoints, ready to deploy.
- **Fast.** 529× faster instantiation than LangGraph. 24× lower memory. [See benchmarks →](#performance)

## Example

An agent with MCP tools, persistent state, served via FastAPI:
```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

agno_agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-5"),
    db=SqliteDb(db_file="agno.db"),
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(agents=[agno_agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agno_agent:app", reload=True)
```

Run this and connect to the [AgentOS UI](https://os.agno.com):

https://github.com/user-attachments/assets/feb23db8-15cc-4e88-be7c-01a21a03ebf6

## Features

**Core**
- Model-agnostic: OpenAI, Anthropic, Google, local models
- Type-safe I/O with `input_schema` and `output_schema`
- Async-first, built for long-running tasks
- Natively multimodal (text, images, audio, video, files)

**Memory & Knowledge**
- Persistent storage for session history and state
- User memory across sessions
- Agentic RAG with 20+ vector stores, hybrid search, reranking
- Culture: shared long-term memory across agents

**Orchestration**
- Human-in-the-loop (confirmations, approvals, overrides)
- Guardrails for validation and security
- Pre/post hooks for the agent lifecycle
- First-class MCP and A2A support
- 100+ built-in toolkits

**Production**
- Ready-to-use FastAPI runtime
- Integrated control plane UI
- Evals for accuracy, performance, latency
- Durable execution for resumable workflows
- RBAC and per-agent permissions

## Getting Started

1. Follow the [quickstart guide](https://github.com/agno-agi/agno/tree/main/cookbook/00_quickstart)
2. Browse the [cookbook](https://github.com/agno-agi/agno/tree/main/cookbook) for real-world examples
3. Read the [docs](https://docs.agno.com) to go deeper

## Performance

Agent workloads spawn hundreds of instances. Stateless, horizontal scalability isn't optional.

| Metric | Agno | LangGraph | PydanticAI | CrewAI |
|--------|------|-----------|------------|--------|
| Instantiation | **3μs** | 1,587μs (529×) | 170μs (57×) | 210μs (70×) |
| Memory | **6.6 KiB** | 161 KiB (24×) | 29 KiB (4×) | 66 KiB (10×) |

<sub>Apple M4 MacBook Pro, Oct 2025. [Run benchmarks yourself →](https://github.com/agno-agi/agno/tree/main/cookbook/12_evals/performance)</sub>

https://github.com/user-attachments/assets/54b98576-1859-4880-9f2d-15e1a426719d

## IDE Integration

Add our docs to your AI-enabled editor:

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

Also works with VSCode, Windsurf, and similar tools.

## Contributing

We welcome contributions. See the [contributing guide](https://github.com/agno-agi/agno/blob/v2.0/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
