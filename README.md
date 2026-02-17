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
  Build multi-agent systems with streaming, memory, governance, and request isolation.
</p>

<div align="center">
  <a href="https://docs.agno.com">Docs</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://www.agno.com/discord">Discord</a>
</div>

## What is Agno?

Agno is the open-source stack for building, deploying and managing multi-agent systems.

Agentic software operates under a different contract than traditional software. Execution is dynamic. Decisions are contextual. Trust must be engineered.

Agno gives you the primitives, execution engine, and production runtime to handle that natively.

| Layer | What it does |
|-------|--------------|
| **SDK** | The primitives: agents, teams, workflows, memory, knowledge, tools, guardrails, approval flows. |
| **Engine** | The agent loop: model calls, tool execution, context management, runtime checks. |
| **AgentOS** | The production runtime: streaming APIs, authentication, per-request isolation, approval enforcement, background execution, and a [control plane](https://os.agno.com) to monitor and manage everything. |

## Why Agno?

Agentic software introduces three fundamental shifts.

### 1. A new interaction model

Traditional software receives a request and returns a response.

Agents stream reasoning, tool calls, and results in real time. They can pause mid-execution, wait for approval, and resume later.

Agno treats streaming and long-running execution as first-class behavior.

### 2. A new governance model

Traditional systems execute predefined decision logic written in advance.

Agents choose actions dynamically. Some actions are low risk. Some require user approval. Some require administrative authority.

Agno lets you define who decides what as part of the agent definition, with:

- Approval workflows
- Human-in-the-loop
- Audit logs
- Enforcement at runtime

### 3. A new trust model

Traditional systems are designed to be predictable. Every execution path is defined in advance.

Agents introduce probabilistic reasoning into the execution path.

Agno builds trust into the engine itself:

- Guardrails run as part of execution
- Evaluations integrate into the agent loop
- Traces and audit logs are first-class

## Built for Production

Agno is not a hobby project. It is designed for real systems.

- 50+ APIs out of the box
- Per-user session isolation
- Stateless, horizontally scalable runtime
- Approval enforcement at runtime
- Background execution and scheduler
- Complete auditability and observability
- Runs entirely in your cloud
- Sessions, memory, knowledge, and traces stored in your database

## Quick Start

Build an agent that answers questions about Agno, remembers past conversations, and runs as a production API:

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

agno_assist = Agent(
    name="Agno Assist",
    model=Claude(id="claude-sonnet-4-5"),
    db=SqliteDb(db_file="agno.db"),
    tools=[MCPTools(url="https://docs.agno.com/mcp")],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(agents=[agno_assist])
app = agent_os.get_app()
```

Run it:

```bash
uv pip install -U 'agno[os]' anthropic mcp

fastapi dev agno_assist.py
```

You get:
- Streaming responses
- Per-user session isolation
- A full API at http://localhost:8000

Connect the [AgentOS UI](https://os.agno.com) to monitor, manage, and test your agents.

## What You Can Build

**Gcode**: a lightweight coding agent that writes, reviews, and iterates on code. It remembers project conventions, learns from its mistakes, and gets sharper the more you use it.

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools
from agno.tools.reasoning import ReasoningTools

gcode = Agent(
    name="Gcode",
    model=OpenAIResponses(id="gpt-5.2"),
    db=SqliteDb(db_file="agno.db"),
    instructions=instructions,
    knowledge=gcode_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=gcode_learnings,
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    tools=[CodingTools(base_dir=workspace, all=True), ReasoningTools()],
    enable_agentic_memory=True,
    add_history_to_context=True,
    num_history_runs=10,
    markdown=True,
)
```

Knowledge, learning, memory, governance and tools are part of the agent definition. They are primitives in Agno.

[Read more →](https://docs.agno.com/deploy/templates/gcode/overview)

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
