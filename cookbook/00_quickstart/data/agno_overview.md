# Agno Overview

Agno is a framework and runtime for building, running, and managing agent
platforms.

## The Stack

- **Agno SDK**: Define agents, teams, workflows, tools, knowledge, memory, and
  learning in Python.
- **AgentOS runtime**: Serve those components through production APIs with
  sessions, streaming, tracing, and human approval.
- **AgentOS UI**: Connect to an AgentOS endpoint to chat with components and
  inspect sessions, traces, knowledge, memory, and learning.

Agno is model-agnostic. An agent combines a model with instructions, tools, and
optional context such as knowledge or memory.

## Minimal Tool-Using Agent

```python
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=Gemini(id="gemini-3.6-flash"),
    tools=[YFinanceTools()],
)

agent.print_response("What's AAPL's current price?", stream=True)
```

## Choosing a Building Block

- Start with an **Agent** for one coherent job.
- Use a **Team** when independent specialists or perspectives improve the
  result enough to justify extra latency and cost.
- Use a **Workflow** when steps must execute in an explicit, repeatable order.
- Use **AgentOS** to run and inspect the complete system.

## Data Ownership

Agno applications can keep sessions, memory, knowledge, and traces in databases
the application owner controls. Production deployments should use appropriate
authentication, authorization, tenant isolation, and durable storage.

## Where to Go Next

- Documentation: https://docs.agno.com
- Repository: https://github.com/agno-agi/agno
- Quickstart: `cookbook/00_quickstart/`
