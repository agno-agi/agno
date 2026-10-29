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
  The self-driving agent platform<br/>
</p>

## Introduction

Agno is a self-driving agent platform. Build agents for your product, your company, or your customers. Run them as durable services on AgentOS. Put them to work automating company operations.

- **Build** agents with the Agno, Claude Agent, or Codex SDKs. Combine agents into teams and workflows.
- **Run** agents as durable services with built-in API and MCP. AgentOS handles authentication, role-based access, resume/replay, human approvals, scheduling, and durable execution.
- **Automate** company operations with Company OS. Give agents responsibilities, organize work into projects and tasks, and configure recurring routines. People set direction and review results; agents own and execute.

Agno provides the orchestration and service layer around your agents, making them available in:

1. **Your product:** using the REST API.
2. **Claude and ChatGPT:** using the MCP server.
3. **Chat apps like Slack:** using Agno Interfaces.

Run your platform in your own cloud and keep your data in your control. Review conversations, inspect traces, manage knowledge, and track your agent activity using the [AgentOS UI](https://os.agno.com).

## Your agent platform

Build with any SDK. Run with AgentOS. Manage with the Control Plane.

| Layer | What it provides |
|---|---|
| **SDK** | Build agents with the Agno, Claude Agent, or Codex SDKs. |
| **AgentOS** | Run your agents as secure, durable services with an API and MCP server. |
| **Control Plane** | Monitor runs, inspect sessions, and manage your platform using the [AgentOS UI](https://os.agno.com). |

## Get started

Agno is built for coding agents. Start with a pre-built template and give this prompt to your coding agent:

```text
Help me set up my agent platform and build my first agent.

Clone https://github.com/agno-agi/agentos-railway into a folder called agent-platform, cd into it, and follow .agents/skills/setup-platform/SKILL.md.
```

The setup skill runs your platform locally and helps you build your first agent. You get:

- An API server and MCP server.
- PostgreSQL storage for conversations, memory, and platform activity.
- OS Manager to help build and manage your platform.
- Claude and Codex engineers to work on your code.
- Skills for building, evaluating, and improving agents.
- A Company workspace for organizing ongoing work, with a daily maintenance routine that reviews your codebase and Agno releases and proposes platform improvements.

Connect your platform to [os.agno.com](https://os.agno.com) to start using it. Build agents with code, use the no-code UI, or chat with the OS Manager.

Start improving your agents and platform with the `/improve` skill. Keep useful changes and regression tests so each round builds on the last. When you're ready, configure scheduled improvement runs in a sandbox that return pull requests for review.

## Templates for every cloud

Choose a template for your cloud: [Docker](https://github.com/agno-agi/agentos-docker) · [Railway](https://github.com/agno-agi/agentos-railway) · [AWS](https://github.com/agno-agi/agentos-aws) · [GCP](https://github.com/agno-agi/agentos-gcp) · [Azure](https://github.com/agno-agi/agentos-azure) · [Fly.io](https://github.com/agno-agi/agentos-fly) · [Render](https://github.com/agno-agi/agentos-render) · [Modal](https://github.com/agno-agi/agentos-modal) · [Helm](https://github.com/agno-agi/agentos-helm)

## What's included

| Capability | What you can do |
|---|---|
| **Agents, teams, and workflows** | Build agents with routing, branching, loops, and parallel execution. |
| **Memory and knowledge** | Give agents long-term memory and access to your documents and data. |
| **Tools and integrations** | Connect agents to external services, databases, and MCP servers. |
| **Durable execution** | Run background work with persistent execution state. |
| **Human approval** | Pause work for review and resume after approval. |
| **Observability** | Inspect conversations, tool calls, traces, and evaluation results. |
| **Scheduling** | Run agents and workflows on a schedule. |
| **Security** | Configure authentication, role-based access, and user isolation. |
| **Coding agents and sandboxes** | Put Claude and Codex to work implementing and testing changes. |
| **Company** | Organize Products, Projects, Tasks, and recurring improvement routines. |

## Tutorials

First, [add Agno to your coding agent](https://docs.agno.com/coding-agents) so it can read the tutorials as you build. Then, learn how to:

- [Build your agent platform](https://docs.agno.com/agent-platform/overview)
- [Serve agents as an API](https://docs.agno.com/tutorials/agents-as-api)
- [Serve agents over MCP](https://docs.agno.com/tutorials/agents-as-mcp)
- [Run Claude and Codex as services](https://docs.agno.com/tutorials/harnesses-as-a-service)
- [Read the documentation](https://docs.agno.com)

## Community

Follow [Agno on X](https://x.com/AgnoAgi) for releases and demos, or subscribe to [The Agno Loop](https://www.agno.com/the-agno-loop-newsletter).

See the [contributing guide](CONTRIBUTING.md) to contribute.

## License

Agno is distributed under the [Apache 2.0 license](LICENSE).

## Telemetry

Agno sends a telemetry event per agent so we know which model providers to prioritize. Prompts, messages, and outputs are never sent. Disable by setting `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
