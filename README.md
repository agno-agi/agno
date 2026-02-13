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
  Build multi-agent systems that learn.
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

**A framework for building multi-agent systems that learn and improve with every interaction.**

Most agents are stateless. They reason, respond, forget. Session history helps, but they're exactly as capable on day 1000 as they were on day 1.

Agno agents are different. They remember users across sessions, accumulate knowledge across conversations, and learn from decisions. Insights from one user benefit everyone. The system gets smarter over time.

Everything runs in your cloud. Your data never leaves your environment.

## Quick Example

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=SqliteDb(db_file="tmp/agents.db"),
    learning=True,
)
```

One line. Your agent now remembers users, accumulates knowledge, and improves over time.

## Production Stack

Agno provides the complete infrastructure for building multi-agent systems that learn:

| Layer | What it does |
|-------|--------------|
| **Framework** | Build agents with learning, tools, knowledge, and guardrails |
| **Runtime** | Run in production using [AgentOS](https://docs.agno.com/agent-os/introduction) |
| **Control Plane** | Monitor and manage via the [AgentOS UI](https://os.agno.com) |

## Get Started

1. [Build your first agent](https://docs.agno.com/first-agent)
2. [Build your first multi-agent system](https://docs.agno.com/first-multi-agent-system)
3. [Deploy to production](https://docs.agno.com/production/overview)

More: [Docs](https://docs.agno.com) · [Cookbook](https://github.com/agno-agi/agno/tree/main/cookbook)

## Features

| Category | What you get |
|----------|--------------|
| **Learning** | User profiles that persist across sessions. User memories that accumulate over time. Learned knowledge that transfers across users. Always or agentic learning modes. |
| **Core** | Model-agnostic: OpenAI, Anthropic, Google, local models. Type-safe I/O with `input_schema` and `output_schema`. Async-first, built for long-running tasks. Natively multimodal (text, images, audio, video, files). |
| **Knowledge** | Agentic RAG with 20+ vector stores, hybrid search, reranking. Persistent storage for session history and state. |
| **Orchestration** | Human-in-the-loop (confirmations, approvals, overrides). Guardrails for validation and security. First-class MCP and A2A support. 100+ built-in toolkits. |
| **Production** | Ready-to-use FastAPI runtime. Integrated control plane UI. Evals for accuracy, performance, latency. |

## IDE Integration

Add our docs to your AI-enabled editor:

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

Also works with VSCode, Windsurf, and similar tools.

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
