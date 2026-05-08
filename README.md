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
  Build, run, and manage agent platforms.<br/>
</p>

## Introduction

Agno provides software for building, running, and managing agent platforms.
- Build agents using any agent framework.
- Run them as production services with session management, tracing, scheduling, and RBAC.
- Manage your platform using a single control plane.

Agno has a 3-layer architecture. Everything except the control plane is free and open-source.

| Layer | Use it to |
|-------|--------------|
| **SDK** | Build agents, multi-agent teams, and agentic workflows. |
| **Runtime** | Run your agents, teams, and workflows as a service. |
| **Control Plane** | Manage your platform using the [AgentOS UI](https://os.agno.com). |

## Example: coding agent as a service

Here's how to run a coding agent as a service.

### Built using the Agno SDK

Save this file as `workbench.py`:

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

# Serve using AgentOS → streaming, auth, session isolation, API endpoints
agent_os = AgentOS(
    agents=[workbench],
    tracing=True,
    db=SqliteDb(db_file="agno.db")
)
app = agent_os.get_app()
```

`Workspace(".")` scopes the agent to the current directory. `read`, `list`, and `search` run freely; `write`, `edit`, `delete`, and `shell` require human approval.

<details>
<summary><strong>Built using the Claude Agent SDK</strong></summary>

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
</details>

### Run it

```bash
uv pip install -U 'agno[os]' openai

export OPENAI_API_KEY=sk-***

fastapi dev workbench.py
```

In 30 lines of code, you get:

- A FastAPI backend with 50+ endpoints
- Streaming responses, persistent sessions, per-user isolation
- Cron scheduling, human approval flows, and RBAC
- Native OpenTelemetry tracing

API is available at `http://localhost:8000` and OpenAPI spec at `http://localhost:8000/docs`.

### Manage your platform using the AgentOS UI

You can use the [AgentOS UI](https://os.agno.com) to manage your agent platform. Use it to test your agents, inspect runs, view traces, manage sessions, and monitor the health of the system. It's free to use with a local AgentOS.

1. Open [os.agno.com](https://os.agno.com) and sign in.
2. Click **"Connect OS"**.
3. Select **"Local"** to connect to a local AgentOS.
4. Enter your endpoint URL (default: `http://localhost:8000`).
5. Name it "Local AgentOS" and click **"Connect"**.

Open Chat, select your agent, and ask:

> Tell me more about the project and the key files

The agent reads your workspace and answers grounded in what it actually finds. Try a follow-up like "create a NOTES.md with three key takeaways." The run pauses for your approval before the file is written, since `write` is in the confirm list.

https://github.com/user-attachments/assets/adb38f55-1d9d-463e-8ca9-966bb6bdc37a

## Get started

Choose whichever path suits you best:
- [Read the docs](https://docs.agno.com)
- [Build your first agent](https://docs.agno.com/first-agent)
- [Start from a template](https://docs.agno.com/tutorials/pick-a-template)
  - [Coda →](https://docs.agno.com/tutorials/coda/overview) A code companion that lives in Slack and works alongside your team.
  - [Dash →](https://docs.agno.com/tutorials/dash/overview) A self-learning data agent that grounds answers in your business context.
  - [Scout →](https://docs.agno.com/tutorials/scout/overview) An agent that navigates information sources like Slack, Google Drive, and Notion to assemble answers.
- [Start from a blank canvas](https://docs.agno.com/tutorials/starter/overview). Build on top of the leanest agent platform template.

## Agno features

- [**Production API**](https://docs.agno.com/runtime/serve-as-api). 50+ endpoints with SSE and websockets make it easy to build a product on top of your agent platform.
- [**Storage**](https://docs.agno.com/runtime/storage). Store sessions, memory, knowledge, and traces in your own database. Use postgres for quick read/write data like sessions and memory. Use clickhouse for OLAP data like traces.
- [**100+ integrations**](https://docs.agno.com/tools/toolkits/overview). Integrate with 100+ tools using pre-built toolkits.
- [**Context Providers**](https://docs.agno.com/runtime/context). Use strategies like context providers to access live data stored in Slack, Drive, wikis, MCP, and custom sources.
- [**Human approval**](https://docs.agno.com/runtime/human-approval). Built in mechanisms for pausing runs for user confirmation up to blocking tools that require admin approval.
- [**Observability**](https://docs.agno.com/runtime/observability). Get monitoring via OpenTelemetry tracing, run history, and audit logs out of the box.
- [**Security**](https://docs.agno.com/runtime/security-and-auth). Get JWT-based RBAC and multi-user, multi-tenant isolation out of the box.
- [**Interfaces**](https://docs.agno.com/runtime/interfaces). Expose your agents via Slack, Telegram, WhatsApp, Discord, AG-UI, A2A.
- [**Scheduling**](https://docs.agno.com/runtime/scheduling). Cron-based scheduling and background jobs with no external infrastructure.
- [**Deploy anywhere**](https://docs.agno.com/runtime/deploy). Run on any cloud platform that can run a containerized image. Docker, Railway, AWS, GCP.

## Coding agent integration

Two options for using Agno with your coding tools:

1. **Add Agno documentation as an indexed source.**

   For example, in **Cursor:** Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`.

   Also works with VSCode, Windsurf, and similar tools.

2. **Add Agno documentation as an MCP server.**

   Add [docs.agno.com/mcp](https://docs.agno.com/mcp) as an MCP server to your favourite coding agent.

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
