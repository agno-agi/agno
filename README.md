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

Agno is an SDK for building agent platforms.

- Build agents using any agent framework.
- Run them as production services with tracing, scheduling, and RBAC.
- Manage using a single control plane.

Agno allows you to own your agent stack. Maintain control of your data, context, tools, permissions, memory and human-review loops. Run your platform in your cloud, and manage it using a beautiful UI.

<img width="3192" height="2038" alt="demo-os" src="https://github.com/user-attachments/assets/6d21e6bc-111f-4b81-ba29-6550fead89b2" />

## What you can build

Agno can bring any agent to life, here are some examples:

- [Coda →](https://docs.agno.com/tutorials/coda/overview) A code companion that lives in Slack and works alongside your team.
- [Dash →](https://docs.agno.com/tutorials/dash/overview) A self-learning data agent that grounds answers in 6 layers of context.
- [Scout →](https://docs.agno.com/tutorials/scout/overview) A context agent that navigates Slack and Google Drive to answer questions.
- [Auto Improving Agent Platform →](https://docs.agno.com/tutorials/starter/overview) Build your own agent platform with an auto-improvement loop.

## Get started

- [Read the docs](https://docs.agno.com)
- [Build your first agent in 20 lines of code.](https://docs.agno.com/first-agent)
- [Build an auto-improving agent platform managed entirely by claude code.](https://docs.agno.com/tutorials/starter/overview)

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
- [Newsletter](https://www.agno.com/the-agno-loop-newsleter): monthly updates on what's shipping

## Contributing

See the [contributing guide](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md).

## Telemetry

Agno logs which model providers are used to prioritize updates. Disable with `AGNO_TELEMETRY=false`.

<p align="right"><a href="#top">↑ Back to top</a></p>
