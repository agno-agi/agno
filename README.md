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
  The programming language for agentic software.
</p>

<div align="center">
  <a href="https://docs.agno.com">Docs</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  <span>&nbsp;•&nbsp;</span>
  <a href="https://www.agno.com/discord">Discord</a>
</div>

## What is Agno?

Agno is the programming language for agentic software.

It provides the complete stack for building, running, and deploying multi-agent systems.

| Layer | What it does |
|-------|--------------|
| **SDK** | The primitives: agents, teams, workflows, memory, knowledge, guardrails, and governance. |
| **Engine** | The agent loop: model calls, tool execution, context management, runtime checks. |
| **AgentOS** | The production runtime: streaming, authentication, request isolation, approval enforcement, background execution, and a [control plane](https://os.agno.com) to monitor and manage everything. |

## Why Agno?

Agentic software operates under a different contract than traditional software.

**A new interaction model.** Traditional software accepts requests and returns responses. Agents stream reasoning, tool calls, and results in real time. They can pause mid-execution, wait for input or approval, and resume days later. Agno supports this natively.

**A new governance model.** Traditional software executes instructions. There's nothing to decide, so there's nothing to govern. Agents make decisions, and some decisions can be made freely, some need user approval, and some need admin approval. Agno lets you express who decides what as part of the agent definition, with approval workflows, human-in-the-loop, and audit logs built in.

**A new trust model.** Traditional software is predictable. Same input, same output, every time. Agents aren't. So the system has to monitor itself. Agno runs guardrails and evaluations as part of the engine.

Everything runs in your cloud. Your data never leaves your environment.

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

Streaming responses, per-user session isolation, and a full API at `http://localhost:8000`.

Connect the [AgentOS UI](https://os.agno.com) to monitor, manage, and test your agents.

## What You Can Build

**Gcode** is a coding agent that writes, reviews, and iterates on code. It remembers project conventions, learns from its mistakes, and gets sharper the more you use it.

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

Knowledge, learning, memory, and tools are part of the agent definition. They're primitives in Agno.

[See the full example →](https://docs.agno.com/deploy/gcode)

## Get Started

1. [Read the docs](https://docs.agno.com)
2. [Build your first agent](https://docs.agno.com/first-agent)
3. [Build your first multi-agent system](https://docs.agno.com/first-multi-agent-system)

Check out the [cookbook](https://github.com/agno-agi/agno/tree/main/cookbook) for more examples.

## IDE Integration

Add agno docs as a source to your coding tools:

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

Also works with VSCode, Windsurf, and similar tools.

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
