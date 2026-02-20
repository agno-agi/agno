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
  The programming language for agentic software.<br/>
  Build, run, and manage multi-agent systems at scale.
</p>

<div align="center">
  <a href="https://docs.agno.com">Docs</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://docs.agno.com/first-agent">Quickstart</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://www.agno.com/discord">Discord</a>
</div>

## What is Agno?

Software is shifting from deterministic request–response to reasoning systems that plan, call tools, remember context, and make decisions. Agno is the language for building that software correctly. It provides:

| Layer | Responsibility |
|-------|----------------|
| **SDK** | Agents, teams, workflows, memory, knowledge, tools, guardrails, approval flows |
| **Engine** | Model calls, tool orchestration, structured outputs, runtime enforcement |
| **AgentOS** | Streaming APIs, isolation, auth, approval enforcement, tracing, control plane |

## Quick Start

Build a stateful, tool-using agent and serve it as a production API in ~20 lines.

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

agno_assist = Agent(
    name="Agno Assist",
    model=Claude(id="claude-sonnet-4-6"),
    db=SqliteDb(db_file="agno.db"),
    tools=[MCPTools(url="https://docs.agno.com/mcp")],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(agents=[agno_assist], tracing=True)
app = agent_os.get_app()
```

Run it:

```bash
export ANTHROPIC_API_KEY="***"

uvx --python 3.12 \
  --with "agno[os]" \
  --with anthropic \
  --with mcp \
  fastapi dev agno_assist.py
```

In ~20 lines, you get:
- A stateful agent with streaming responses
- Per-user, per-session isolation
- A production API at http://localhost:8000
- Native tracing

Connect to the [AgentOS UI](https://os.agno.com) to monitor, manage, and test your agents.

1. Open [os.agno.com](https://os.agno.com) and sign in.
2. Click **"Add new OS"** in the top navigation.
3. Select **"Local"** to connect to a local AgentOS.
4. Enter your endpoint URL (default: `http://localhost:8000`).
5. Name it "Local AgentOS".
6. Click **"Connect"**.

https://github.com/user-attachments/assets/75258047-2471-4920-8874-30d68c492683

Open Chat, select your agent, and ask:

> What is Agno?

The agent retrieves context from the Agno MCP server and responds with grounded answers.

https://github.com/user-attachments/assets/24c28d28-1d17-492c-815d-810e992ea8d2

You can use this exact same architecture for running multi-agent systems in production.

## Why Agno?

Agentic software introduces three fundamental shifts.

### A new interaction model

Traditional software receives a request and returns a response. Agents stream reasoning, tool calls, and results in real time. They can pause mid-execution, wait for approval, and resume later.

Agno treats streaming and long-running execution as first-class behavior.

### A new governance model

Traditional systems execute predefined decision logic written in advance. Agents choose actions dynamically. Some actions are low risk. Some require user approval. Some require administrative authority.

Agno lets you define who decides what as part of the agent definition, with:

- Approval workflows
- Human-in-the-loop
- Audit logs
- Enforcement at runtime

### A new trust model

Traditional systems are designed to be predictable. Every execution path is defined in advance. Agents introduce probabilistic reasoning into the execution path.

Agno builds trust into the engine itself:

- Guardrails run as part of execution
- Evaluations integrate into the agent loop
- Traces and audit logs are first-class

## Built for Production

Agno runs in your infrastructure, not ours.

- Stateless, horizontally scalable runtime.
- 50+ APIs and background execution.
- Per-user and per-session isolation.
- Runtime approval enforcement.
- Native tracing and full auditability.
- Sessions, memory, knowledge, and traces stored in your database.

You own the system. You own the data. You define the rules.

## What You Can Build

Agno powers real agentic systems built from the same primitives above.

- [**Pal →**](https://github.com/agno-agi/pal) A personal agent that learns your preferences.
- [**Dash →**](https://github.com/agno-agi/dash) A self-learning data agent grounded in six layers of context.
- [**Scout →**](https://github.com/agno-agi/scout) A self-learning context agent that manages enterprise context knowledge.
- [**Gcode →**](https://github.com/agno-agi/gcode) A post-IDE coding agent that improves over time.
- [**Investment Team →**](https://github.com/agno-agi/investment-team) A multi-agent investment committee that debates and allocates capital.

Single agents. Coordinated teams. Structured workflows. All built on one architecture.

## Get Started

1. [Read the docs](https://docs.agno.com)
2. [Build your first agent](https://docs.agno.com/first-agent)
3. Explore the [cookbook](https://github.com/agno-agi/agno/tree/main/cookbook)

## IDE Integration

Add Agno docs as a source in your coding tools:

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

Also works with VSCode, Windsurf, and similar tools.

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
