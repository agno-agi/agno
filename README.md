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

Agno is a self-driving agent platform. Build agents for your company, product, or customers. Run them as durable services on AgentOS. Put them to work automating company operations.

- **Build** agents with the Agno, Claude Agent, or Codex SDKs. Combine agents into teams and workflows.
- **Run** agents as durable services with built-in API and MCP. AgentOS handles authentication, role-based access, resume/replay, human approvals, scheduling, and durable execution.
- **Automate** company operations with Company OS. Give agents responsibilities, organize work into projects and tasks, and configure recurring routines. People set direction and review results; agents own and execute.

Agno provides the orchestration and service layer around your agents, making them available in:

1. **Your product:** using the REST API.
2. **Claude and ChatGPT:** using the MCP server.
3. **Chat apps like Slack:** using Agno Interfaces.

Run your platform in your own cloud and keep your data in your control. Review conversations, inspect traces, manage knowledge, and track your agent activity using the [AgentOS UI](https://os.agno.com).

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
| --- | --- |
| **[Agents](https://docs.agno.com/agents/overview) and [teams](https://docs.agno.com/teams/overview)** | Build agents that use tools, delegate work, and collaborate. |
| **[Workflows](https://docs.agno.com/workflows/overview)** | Control execution with routing, conditions, loops, and parallel steps. |
| **[Memory](https://docs.agno.com/memory/overview) and [knowledge](https://docs.agno.com/knowledge/overview)** | Remember users across sessions and retrieve answers from your data. |
| **[Tools and integrations](https://docs.agno.com/tools/overview)** | Connect agents to APIs, databases, and MCP servers. |
| **[Durable execution](https://docs.agno.com/agent-os/background-execution/durable-queue)** | Persist background jobs and track their status across restarts. |
| **[Human approval](https://docs.agno.com/hitl/overview)** | Review sensitive actions before they run, then approve and continue. |
| **[Observability](https://docs.agno.com/agent-os/tracing/overview)** | Trace runs, inspect tool calls, and diagnose failures. |
| **[Scheduling](https://docs.agno.com/agent-os/scheduler/overview)** | Run agents, teams, and workflows on recurring schedules. |
| **[Security](https://docs.agno.com/agent-os/security/overview)** | Control access with authentication, roles, and per-user data isolation. |
| **[Coding agents](https://docs.agno.com/agent-platform/harness-agents)** | Run Claude and Codex in sandboxes to implement and test changes. |
| **Company OS** | Organize work into products, projects, tasks, and recurring routines. |

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
