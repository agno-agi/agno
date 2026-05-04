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
  Agno turns agents into production software.<br/>
  Build agents in any framework. Run as a service. Ship to real users.
</p>

<div align="center">
  <a href="https://docs.agno.com">Docs</a>
  &nbsp;•&nbsp;
  <a href="https://github.com/agno-agi/agno/tree/main/cookbook">Cookbook</a>
  &nbsp;•&nbsp;
  <a href="https://docs.agno.com/first-agent">Quickstart</a>
</div>

## What is Agno

Agno is the runtime for agentic software. Use it to run agents as a production service.

Build agents using any framework. Run them as production services with sessions, tracing, scheduling, and RBAC. Manage them from a single control plane.

| Layer | What it does |
|-------|--------------|
| **SDK** | Build agents, teams, and workflows with memory, knowledge, guardrails, and 100+ integrations. |
| **Runtime** | Serve agents in production via a stateless, session-scoped FastAPI backend. |
| **Control Plane** | Test, monitor, and manage your system from the [AgentOS UI](https://os.agno.com). |

## Quick Start

Wrap a coding agent and serve it as a production API. Same shape across every framework.

### With the Agno SDK

Save as `workbench.py`:

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace

workbench = Agent(
    name="Workbench",
    model="openai:gpt-5.4",
    tools=[Workspace(".",
        allowed=["read", "list", "search"],
        confirm=["write", "edit", "delete", "shell"],
    )],
    enable_agentic_memory=True,
    add_history_to_context=True,
    num_history_runs=3,
)

# Serve via AgentOS → streaming, auth, session isolation, API endpoints
agent_os = AgentOS(agents=[workbench], tracing=True, db=SqliteDb(db_file="agno.db"))
app = agent_os.get_app()
```

`Workspace(".")` scopes the agent to the current directory. `read`, `list`, and `search` run freely; `write`, `edit`, `move`, `delete`, and `shell` require human approval.

### With the Claude Agent SDK

```python
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

agent = ClaudeAgent(
    name="Claude Agent",
    model="claude-opus-4-7",
    allowed_tools=["Read", "Bash"],
    permission_mode="acceptEdits",
)

agent_os = AgentOS(agents=[agent], db=SqliteDb(db_file="agno.db"), tracing=True)
app = agent_os.get_app()
```

The same wrapping pattern works for [LangGraph](#) and [DSPy](#).

<details>
<summary><strong>LangGraph</strong></summary>

```python
from agno.agents.langgraph import LangGraphAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph

def chatbot(state: MessagesState):
    return {"messages": [ChatOpenAI(model="gpt-5.4").invoke(state["messages"])]}

graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")

agent = LangGraphAgent(name="LangGraph Chatbot", graph=graph.compile())
agent_os = AgentOS(agents=[agent], db=SqliteDb(db_file="agno.db"), tracing=True)
app = agent_os.get_app()
```

</details>

<details>
<summary><strong>DSPy</strong></summary>

```python
import dspy
from agno.agents.dspy import DSPyAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

dspy.configure(lm=dspy.LM("openai/gpt-5.4"))

agent = DSPyAgent(
    name="DSPy Assistant",
    program=dspy.ChainOfThought("question -> answer"),
)

agent_os = AgentOS(agents=[agent], db=SqliteDb(db_file="agno.db"), tracing=True)
app = agent_os.get_app()
```

</details>

### Run it

```bash
uv pip install -U 'agno[os]' openai

export OPENAI_API_KEY=sk-***

fastapi dev workbench.py
```

In ~20 lines, you get:

- A FastAPI backend with 50+ endpoints
- Streaming responses, persistent sessions, per-user isolation
- Native OpenTelemetry tracing
- Cron scheduling, human approval flows, and RBAC ready to enable

API at `http://localhost:8000`. OpenAPI spec at `http://localhost:8000/docs`.

## Connect to the AgentOS UI

The [AgentOS UI](https://os.agno.com) is your control plane. Use it to chat with your agents, inspect runs, view traces, manage sessions, and operate the system.

1. Open [os.agno.com](https://os.agno.com) and sign in.
2. Click **"Connect OS"**
3. Select **"Local"** to connect to a local AgentOS.
4. Enter your endpoint URL (default: `http://localhost:8000`).
5. Name it "Local AgentOS" and click **"Connect"**.

Open Chat, select your agent, and ask:

> Tell me more about the project and the key files

The agent reads your workspace and answers grounded in what it actually finds. Try a follow-up like "create a NOTES.md with three key takeaways". The run pauses for your approval before the file is written, since `write_file` is a confirm-required tool by default.

https://github.com/user-attachments/assets/adb38f55-1d9d-463e-8ca9-966bb6bdc37a

## What AgentOS gives you

- [**Production API**](https://docs.agno.com/runtime/serve-as-api). 50+ endpoints with SSE and websockets to build your product on.
- [**Storage**](https://docs.agno.com/runtime/storage). Sessions, memory, knowledge, and traces in your own database.
- [**Context**](https://docs.agno.com/runtime/context). Live context across Slack, Drive, wikis, MCP, and custom sources.
- [**Human approval**](https://docs.agno.com/runtime/human-approval). Pause runs for user confirmation, admin approval, or external execution.
- [**Observability**](https://docs.agno.com/runtime/observability). OpenTelemetry tracing, run history, and audit logs out of the box.
- [**Security & auth**](https://docs.agno.com/runtime/security-and-auth). JWT-based RBAC and multi-user, multi-tenant isolation.
- [**Interfaces**](https://docs.agno.com/runtime/interfaces). Slack, Telegram, WhatsApp, Discord, AG-UI, A2A, or roll your own.
- [**Scheduling**](https://docs.agno.com/runtime/scheduling). Cron-based scheduling and background jobs with no external infrastructure.
- [**Deploy**](https://docs.agno.com/runtime/deploy). Docker, Railway, AWS, GCP. Any container host works.

## What you can build

Three reference agents, all open source, all built on the same primitives:

- [**Coda →**](https://github.com/agno-agi/coda) A Slack-native coding agent that ships PRs from your team chat.
- [**Dash →**](https://github.com/agno-agi/dash) A self-learning data agent grounded in six layers of context.
- [**Scout →**](https://github.com/agno-agi/scout) A self-learning context agent that manages enterprise knowledge.

## Get started

1. [Read the docs](https://docs.agno.com)
2. [Build your first agent](https://docs.agno.com/first-agent)
3. Explore the [cookbook](https://github.com/agno-agi/agno/tree/main/cookbook)

## IDE integration

Add Agno docs as a source in your coding tools:

**Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`

Also works with VSCode, Windsurf, and similar tools.

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
