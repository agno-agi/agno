# Slack Cookbook

Examples for `interfaces/slack` in AgentOS.

## Files
- `agent_with_user_memory.py` — Agent With User Memory.
- `basic.py` — Basic.
- `basic_workflow.py` — Basic Workflow.
- `channel_summarizer.py` — Channel Summarizer.
- `file_analyst.py` — File Analyst.
- `multiple_instances.py` — Multiple Instances.
- `reasoning_agent.py` — Reasoning Agent.
- `research_assistant.py` — Research Assistant.
- `streaming.py` — Streaming (real-time token delivery with tool progress).
- `support_team.py` — Support Team.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
