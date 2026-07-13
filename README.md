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

Agno is a framework and runtime for building agent platforms.

- Build your agent platform using the Agno SDK.
- Run your agent platform using the AgentOS runtime.
- Manage everything using the AgentOS control plane.

Agno allows you to own your agent stack. Maintain control of your data, context, tools, permissions, memory and human-review loops. Run your platform in your own cloud, and manage it using a beautiful UI.

<img width="3192" height="2038" alt="demo-os" src="https://github.com/user-attachments/assets/6d21e6bc-111f-4b81-ba29-6550fead89b2" />

## Get started

- [Read the docs](https://docs.agno.com)
- [Build your first agent in 20 lines of code.](https://docs.agno.com/first-agent)
- [Build your own agent platform.](https://docs.agno.com/agent-platform/overview)

## Features

- [Production API](https://docs.agno.com/runtime/serve-as-api). 50+ endpoints with SSE and websockets to build a product on top.
- [Storage](https://docs.agno.com/runtime/storage). Store sessions, memory, knowledge, and traces in your own database.
- [100+ integrations](https://docs.agno.com/tools/toolkits/overview). Integrate with 100+ tools using pre-built toolkits.
- [Context Providers](https://docs.agno.com/runtime/context). Access live data from Slack, Drive, wikis, MCP, and custom sources.
- [Human approval](https://docs.agno.com/runtime/human-approval). Pause runs for user confirmation. Block tools that require admin approval.
- [Observability](https://docs.agno.com/runtime/observability). Get monitoring via OpenTelemetry tracing, run history, and audit logs out of the box.
- [Security](https://docs.agno.com/runtime/security-and-auth). Get JWT-based RBAC and multi-user, multi-tenant isolation out of the box.
- [Interfaces](https://docs.agno.com/runtime/interfaces). Expose your agents via Slack, Telegram, WhatsApp, Discord, AG-UI, A2A.
- [Scheduling](https://docs.agno.com/runtime/scheduling). Cron-based scheduling and background jobs with no external infrastructure.
- [Deploy anywhere](https://docs.agno.com/runtime/deploy). Run on any cloud platform that runs containers. Docker, Railway, AWS, GCP.

## Use Agno with your coding agent

Two options:

1. Add Agno docs as an indexed source. In Cursor: Settings → Indexing & Docs → Add `https://docs.agno.com/llms-full.txt`. Also works in VSCode, Windsurf, and similar tools.
2. Add Agno docs as an MCP server. Add [docs.agno.com/mcp](https://docs.agno.com/mcp) to your favourite coding agent.

Read the full guide [here](https://docs.agno.com/coding-agents).

## Community

- [X](https://x.com/AgnoAgi): follow for releases and demos
- [Newsletter](https://www.agno.com/the-agno-loop-newsletter): monthly updates on what's shipping

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
