<div align="center" id="top">
  <a href="https://agno.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg">
      <img src="https://agno-public.s3.us-east-1.amazonaws.com/assets/logo-light.svg" alt="Agno">
    </picture>
  </a>
</div>

<div align="center">
  <a href="https://docs.agno.com">Documentation</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="https://www.agno.com/?utm_source=github&utm_medium=readme&utm_campaign=agno-github">Website</a>
  <br />
</div>

## What is Agno?

Agno is a multi-agent framework, runtime, and control plane. Use it to build private and secure AI products that run in your cloud.

- **Build** agents, teams, and workflows with memory, knowledge, guardrails and 100+ integrations.
- **Run** in production with a stateless FastAPI runtime. Horizontally scalable.
- **Manage** with a control plane that connects directly to your runtime — no data leaves your environment.

## Why Agno?

- **Your cloud, your data:** Runs entirely in your infrastructure. Nothing leaves your environment.
- **Ready for production on day one:** Pre-built FastAPI runtime with SSE endpoints, ready to deploy.
- **Incredibly fast:** 529× faster than LangGraph, 24× lower memory.

## Getting Started

Start with the [getting started guide](https://github.com/agno-agi/agno/tree/main/cookbook/00_getting_started), then:

- Browse the [cookbooks](https://github.com/agno-agi/agno/tree/main/cookbook) for real-world examples
- Read the [docs](https://docs.agno.com) to learn more

## Resources

- Docs: <a href="https://docs.agno.com" target="_blank" rel="noopener noreferrer">docs.agno.com</a>
- Cookbook: <a href="https://github.com/agno-agi/agno/tree/main/cookbook" target="_blank" rel="noopener noreferrer">Cookbook</a>
- Community forum: <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">community.agno.com</a>
- Discord: <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">discord</a>

## Example

Here's an example of an Agent that connects to an MCP server, manages conversation state in a database, is served using a FastAPI application that you can chat with using the [AgentOS UI](https://os.agno.com).

```python agno_agent.py
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ************* Create Agent *************
agno_agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-5"),
    # Add a database to the Agent
    db=SqliteDb(db_file="agno.db"),
    # Add the Agno MCP server to the Agent
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
    # Add the previous session history to the context
    add_history_to_context=True,
    markdown=True,
)


# ************* Create AgentOS *************
agent_os = AgentOS(agents=[agno_agent])
# Get the FastAPI app for the AgentOS
app = agent_os.get_app()

# ************* Run AgentOS *************
if __name__ == "__main__":
    agent_os.serve(app="agno_agent:app", reload=True)
```

## AgentOS - Production Runtime for Multi-Agent Systems

Building Agents is easy, running them as a secure, scalable service is hard. AgentOS solves this by providing a high performance runtime for serving multi-agent systems in production. Key features include:

1. **Pre-built FastAPI app**: AgentOS includes a ready-to-use FastAPI app for running your agents, teams and workflows. This gives you a significant head start when building an AI product.

2. **Integrated Control Plane**: The [AgentOS UI](https://os.agno.com) connects directly to your runtime, so you can test, monitor and manage your system in real time with full operational visibility.

3. **Private by Design**: AgentOS runs entirely in your cloud, ensuring complete data privacy. No data leaves your environment, making it ideal for security conscious enterprises..

When you run the example script shared above, you get a FastAPI app that you can connect to the [AgentOS UI](https://os.agno.com). Here's what it looks like in action:

https://github.com/user-attachments/assets/feb23db8-15cc-4e88-be7c-01a21a03ebf6

## Private by Design

This is the part we care most about.

AgentOS runs in **your** cloud. The control plane UI connects directly to your runtime from your browser. Your data never touches our servers. No retention costs, no vendor lock-in, no compliance headaches.

This isn't a privacy mode or enterprise add-on. It's how Agno works.

## Features

### Core:
- Model agnostic — works with OpenAI, Anthropic, Google, local models, whatever
- Type-safe I/O with `input_schema` and `output_schema`
- Async-first, built for long-running tasks
- Natively multimodal (text, images, audio, video, files)

### Memory & Knowledge:
- Persistent storage for session history and state
- User memory that persists across sessions
- Agentic RAG with 20+ vector stores, hybrid search, reranking
- Culture — shared long-term memory across agents

### Execution:
- Human-in-the-loop (confirmations, approvals, overrides)
- Guardrails for validation and security
- Pre/post hooks for the agent lifecycle
- First-class MCP and A2A support
- 100+ built-in toolkits

### Production:
- Ready-to-use FastAPI runtime
- Integrated control plane UI
- Evals for accuracy, performance, latency
- Durable execution for resumable workflows
- RBAC and per-agent permissions

## Performance

We're obsessive about performance because agent workloads spawn hundreds of instances and run long tasks. Stateless, horizontal scalability isn't optional.

**Benchmarks** (Apple M4 MacBook Pro, Oct 2025):

| Metric | Agno | LangGraph | PydanticAI | CrewAI |
|--------|------|-----------|------------|--------|
| Instantiation | **3μs** | 1,587μs (529× slower) | 170μs (57× slower) | 210μs (70× slower) |
| Memory | **6.6 KiB** | 161 KiB (24× higher) | 29 KiB (4× higher) | 66 KiB (10× higher) |

Run the benchmarks yourself: [`cookbook/12_evals/performance`](https://github.com/agno-agi/agno/tree/main/cookbook/12_evals/performance)

https://github.com/user-attachments/assets/54b98576-1859-4880-9f2d-15e1a426719d

## IDE Integration

For AI-assisted development, add our docs to your IDE:

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

Works with VSCode, Windsurf, and other AI-enabled editors too.

## Contributing

We welcome contributions. See the [contributing guide](https://github.com/agno-agi/agno/blob/v2.0/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used so we can prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="left">
  <a href="#top">⬆️ Back to Top</a>
</p>
