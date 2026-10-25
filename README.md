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
  The self-improving platform for agents<br/>
</p>

## Introduction

Agno is a self-improving platform for agents. Build agents. Run them as durable services. Improve them with use.

- **Build** agents with the Agno, Claude Code, or Codex SDKs. Use any model, connect them to your tools and build agents for your product, your team, or your customers. Build agents using code, a no-code UI or by chatting with the OS Manager in your platform. Organize agents into teams or multi-step workflows.
- **Run** your agents as durable services. Get an API and MCP server out of the box. Build products on top of the API or connect your agents to AI applications using MCP. Run your platform in your own cloud, keep all your data in your own database, and manage everything using the [AgentOS UI](https://os.agno.com). Review conversations, inspect traces, manage knowledge, and track your agent activity in one place.
- **Improve** your agents and the platform they run on. Give coding agents access to source code, conversations, traces, and evaluations so they can investigate failures, simulate user scenarios, and test changes to instructions, tools, knowledge, and code. Start by running the `/eval-and-improve` skill in Claude Code or Codex. Retain useful changes and regression tests, and choose which changes to adopt. When you're ready, configure scheduled improvement runs in a sandbox that return pull requests for review.

## Get started

We recommend using our pre-built templates to bootstrap your agent platform.

Give this prompt to your coding agent:

```text
Help me set up my agent platform.

Clone https://github.com/agno-agi/agentos-railway into a folder called agent-platform, cd into it, and follow .agents/skills/setup-platform/SKILL.md.
```

The setup skill runs your platform locally and helps you build your first agent. You get:

- An API server and MCP server.
- PostgreSQL storage for conversations, memory, and platform activity.
- OS Manager to help build and manage your platform.
- Claude and Codex engineers to work on your code.
- Skills for building, evaluating, and improving agents.
- A Company workspace for organizing ongoing work, with a daily maintenance routine that reviews your codebase and Agno releases and proposes platform improvements.

Connect your platform to [os.agno.com](https://os.agno.com) to start using it.

## Deploy to your cloud

Choose a template for your cloud: [Docker](https://github.com/agno-agi/agentos-docker) · [Railway](https://github.com/agno-agi/agentos-railway) · [AWS](https://github.com/agno-agi/agentos-aws) · [GCP](https://github.com/agno-agi/agentos-gcp) · [Azure](https://github.com/agno-agi/agentos-azure) · [Fly.io](https://github.com/agno-agi/agentos-fly) · [Render](https://github.com/agno-agi/agentos-render) · [Modal](https://github.com/agno-agi/agentos-modal) · [Helm](https://github.com/agno-agi/agentos-helm)

### What's included

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

## Learn more

- [Build your first agent](https://docs.agno.com/first-agent)
- [Build your agent platform](https://docs.agno.com/agent-platform/overview)
- [Read the documentation](https://docs.agno.com)
- [Connect the documentation to your coding agent](https://docs.agno.com/coding-agents)

## Community

Follow [Agno on X](https://x.com/AgnoAgi) for releases and demos, or subscribe to [The Agno Loop](https://www.agno.com/the-agno-loop-newsletter).

See the [contributing guide](CONTRIBUTING.md) to contribute.

## License

Agno is distributed under the [Apache 2.0 license](LICENSE).

## Telemetry

Agno sends a telemetry event per agent so we know which model providers to prioritize. Prompts, messages, and outputs are never sent. Disable by setting `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
