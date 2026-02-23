# Slack Cookbook

Examples for connecting Agno agents, teams, and workflows to Slack using the
`Slack` interface in AgentOS. Supports both standard request/response and
real-time streaming via Slack's `chat_stream` API.

## Getting Started

- `basic.py` — Minimal agent that responds to @mentions with session history.
- `basic_workflow.py` — Two-step research-then-write workflow in Slack.

## Streaming

Streaming requires the `assistant:write` scope and the `assistant_thread_started`
event subscription. Tokens arrive in real-time and tool calls render as progress
cards in Slack's plan display.

- `streaming.py` — Agent with tool progress cards, thread titles, and suggested prompts.
- `streaming_research.py` — Research agent with multiple tools and rich plan-block cards.
- `streaming_deep_research.py` — Deep research agent with 7 toolkits stress-testing plan display.
- `streaming_team.py` — Multi-agent stock research team with streaming.

## Teams and Workflows

- `support_team.py` — Support team routing questions to Technical Support or Documentation Specialist.
- `multimodal_team.py` — Team with GPT-4o vision input and DALL-E image output.
- `multimodal_workflow.py` — Parallel visual analysis + web research, then creative synthesis.

## Tools and Features

- `agent_with_user_memory.py` — Agent with MemoryManager that learns about users over time.
- `channel_summarizer.py` — Agent that reads channel history and summarizes threads.
- `file_analyst.py` — Agent that downloads, analyzes, and uploads files via SlackTools.
- `reasoning_agent.py` — Agent with ReasoningTools for step-by-step thinking.
- `research_assistant.py` — Agent combining Slack message search with web search.
- `multiple_instances.py` — Two bots on one server with separate credentials.

## Testing

- `test_all.py` — Two apps (workflow + team) on one server for comprehensive testing.
- `test_streaming_events.py` — Switch between agent/team/workflow with `TEST_MODE` env var.

## Prerequisites

1. **Slack App** — Create an app at https://api.slack.com/apps.
2. **Environment variables:**
   - `SLACK_TOKEN` — Bot User OAuth Token (`xoxb-...`)
   - `SLACK_SIGNING_SECRET` — Signing Secret from the app's Basic Information page
3. **Required scopes:** `chat:write`, `app_mentions:read`, `im:history`
   - Streaming adds: `assistant:write`
   - File examples add: `files:read`, `files:write`
   - User lookup adds: `users:read`
4. **Event subscriptions:** `app_mention`, `message.im`
   - Streaming adds: `assistant_thread_started`
5. **Tunnel** — Use ngrok or similar: `ngrok http 7777`
6. **Set Event URL** to `https://<ngrok-url>/slack/events` (or `/prefix/events` for multi-instance).

## Running

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/<file>.py
```
