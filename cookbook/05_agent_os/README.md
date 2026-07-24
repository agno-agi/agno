# AgentOS Cookbook

This folder is being reorganized into a numbered AgentOS curriculum. Phase 0
removes duplicate examples and moves integration- and tool-specific lessons to
their canonical cookbook homes; the existing unnumbered lessons remain
available until their numbered replacements land in later phases.

## Start here

Run the current entrypoint server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/basic.py
```

Then open [http://localhost:7777/config](http://localhost:7777/config) to see
the AgentOS configuration exposed to clients and the control plane.

## Phase 0 migrations

- Discord integration coverage now lives in
  `cookbook/integrations/discord/`.
- AgentOS-managed dynamic MCP headers now live with the MCP client examples in
  `cookbook/91_tools/mcp/dynamic_headers/`.
- Duplicate model, tool, schema, guardrail, follow-up, and workflow-as-step
  examples were removed in favor of their canonical cookbooks.

The numbered lesson index is added incrementally beginning in Phase 1.

## Prerequisites

- Load environment variables with `direnv allow` when available.
- Run cookbook examples with `.venvs/demo/bin/python`.
- Individual lessons document any additional API keys or local services they
  require.
