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

Agno is a framework and runtime for agent platforms. Build agents, run them as a service, manage your platform using a web UI.

- Build your agent platform using the Agno SDK.
- Run your agent platform using the AgentOS runtime.
- Manage everything using the AgentOS UI.

Agno allows you to own your agent stack. Maintain control of your data, memory, and security posture (JWT-based RBAC), and turn your agent platform into a learning loop with simulations and usage data.

<img width="3192" height="2038" alt="demo-os" src="https://github.com/user-attachments/assets/6d21e6bc-111f-4b81-ba29-6550fead89b2" />

## Get started

Hand this prompt to your coding agent (Claude Code, Cursor, Codex):

```text
Help me set up my agent platform.

Clone https://github.com/agno-agi/agentos-railway into a folder called
agent-platform, cd in, read the README, and follow the get started guide.
```

Your coding agent will set up your agent platform and run it locally using Docker, giving you a REST API for serving your agents, a Postgres database for storing your data and traces, an MCP server, and a control plane.

Deploying somewhere else? Use the same prompt but point it to a different repo. The starter templates are identical except for the deploy scripts: swap [agentos-railway](https://github.com/agno-agi/agentos-railway) for [agentos-docker](https://github.com/agno-agi/agentos-docker), [agentos-aws](https://github.com/agno-agi/agentos-aws), [agentos-gcp](https://github.com/agno-agi/agentos-gcp), [agentos-azure](https://github.com/agno-agi/agentos-azure), [agentos-fly](https://github.com/agno-agi/agentos-fly), [agentos-render](https://github.com/agno-agi/agentos-render), [agentos-modal](https://github.com/agno-agi/agentos-modal), or [agentos-helm](https://github.com/agno-agi/agentos-helm).

### Prefer to code by hand?

- [Build your first agent in 20 lines of code.](https://docs.agno.com/first-agent)
- [Build your own agent platform.](https://docs.agno.com/agent-platform/overview)
- [Read the docs.](https://docs.agno.com)

## Features

- [Production API](https://docs.agno.com/runtime/serve-as-api). 50+ endpoints with SSE and websockets to build a product on top.
- [Storage](https://docs.agno.com/runtime/storage). Store sessions, memory, knowledge, and traces in your own database.
- [100+ integrations](https://docs.agno.com/tools/toolkits/overview). Connect to GitHub, Slack, Postgres, and more using pre-built toolkits.
- [Context Providers](https://docs.agno.com/runtime/context). Access live data from Slack, Drive, wikis, MCP, and custom sources.
- [Human approval](https://docs.agno.com/runtime/human-approval). Pause runs for user confirmation. Block tools that require admin approval.
- [Observability](https://docs.agno.com/runtime/observability). Monitor with OpenTelemetry tracing, run history, and audit logs.
- [Security](https://docs.agno.com/runtime/security-and-auth). Get JWT-based RBAC and multi-user, multi-tenant isolation out of the box.
- [Interfaces](https://docs.agno.com/runtime/interfaces). Expose your agents via Slack, Telegram, WhatsApp, Discord, AG-UI, A2A.
- [Scheduling](https://docs.agno.com/runtime/scheduling). Cron-based scheduling and background jobs with no external infrastructure.
- [Deploy anywhere](https://docs.agno.com/runtime/deploy). Run on any cloud platform that runs containers. Docker, Railway, AWS, GCP.

## Use Agno with your coding agent

Two options:

1. Recommended: Add Agno docs as an MCP server. Add [docs.agno.com/mcp](https://docs.agno.com/mcp) to your favourite coding agent.
2. Add Agno docs as an indexed source. In Cursor: Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`. Also works in VSCode, Windsurf, and similar tools.

Read the full guide [here](https://docs.agno.com/coding-agents).

## Community

- [X](https://x.com/AgnoAgi): follow for releases and demos
- [Newsletter](https://www.agno.com/the-agno-loop-newsletter): monthly updates on what's shipping

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## License

Agno is distributed under the [Apache-2.0 license](LICENSE).

## Telemetry

Agno sends a telemetry event per agent run so we know which model providers to prioritize. Prompts, messages, and outputs are never sent. Disable by setting `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
