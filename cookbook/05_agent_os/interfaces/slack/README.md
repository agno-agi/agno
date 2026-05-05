# Slack Cookbook

Examples for connecting Agno agents, teams, and workflows to Slack using the
`Slack` interface in AgentOS. Supports both standard request/response and
real-time streaming via Slack's `chat_stream` API.

**Requirements:** `slack_sdk >= 3.40.0` (streaming with plan-mode task cards).
Install or upgrade with `pip install "slack_sdk>=3.40.0"`.

## Slack App Setup

Follow these steps to create and configure a Slack app for use with Agno.

### 1. Create the App

1. Go to https://api.slack.com/apps and click **Create New App**.
2. Choose **From scratch**, give it a name, and select your workspace.
3. On the **Basic Information** page, copy the **Signing Secret** — you'll need it later.

### 2. Enable Agents & AI Apps (required for streaming)

1. In the sidebar, click **Agents & AI Apps**.
2. Toggle **Agent or Assistant** to **On**.
3. Under **Suggested Prompts**, select **Dynamic** (lets the server set prompts via API).
4. Click **Save**.

> Enabling this automatically adds the `assistant:write` scope.

### 3. Add OAuth Scopes

1. In the sidebar, click **OAuth & Permissions**.
2. Scroll to **Scopes > Bot Token Scopes** and add:

| Scope | Purpose |
|-------|---------|
| `app_mentions:read` | Receive @mention events |
| `assistant:write` | Streaming (startStream/appendStream/stopStream) |
| `chat:write` | Send messages and stream responses |
| `im:history` | Read DM history for thread context |
| `channels:history` | Read public channel history |
| `groups:history` | Read private channel history |
| `files:read` | Download files users send to the bot |
| `files:write` | Upload response files (images, docs) |
| `users:read` | Look up user info (for channel_summarizer, etc.) |
| `search:read` | Search workspace messages (research_assistant, support_team, etc.) |

Not all scopes are needed for every example — `app_mentions:read`, `assistant:write`,
`chat:write`, and `im:history` are the minimum for streaming. Each cookbook's docstring
lists the exact scopes it requires.

3. Scroll up and click **Install to Workspace** (or **Reinstall** if updating scopes).
4. Copy the **Bot User OAuth Token** (`xoxb-...`).

### 4. Subscribe to Events

1. In the sidebar, click **Event Subscriptions**.
2. Toggle **Enable Events** to **On**.
3. Set **Request URL** to your tunnel URL + `/slack/events`:
   ```
   https://<your-tunnel>/slack/events
   ```
   Slack will send a challenge request — the server must be running to verify.
4. Under **Subscribe to bot events**, add:

| Event | Purpose |
|-------|---------|
| `app_mention` | Respond to @mentions in channels |
| `message.im` | Respond to direct messages |
| `message.channels` | Respond to messages in public channels |
| `message.groups` | Respond to messages in private channels |
| `assistant_thread_started` | Set suggested prompts when a thread opens |
| `assistant_thread_context_changed` | Update context when thread is moved |

5. Click **Save Changes**.
6. Go to **Install App** and click **Reinstall to Workspace** to apply the new events.

### 5. Set Environment Variables

```bash
export SLACK_TOKEN="xoxb-..."               # Bot User OAuth Token from step 3
export SLACK_SIGNING_SECRET="..."           # Signing Secret from step 1
export OPENAI_API_KEY="sk-..."              # Or whichever model provider you use
```

### 6. Start a Tunnel

Slack needs a public URL to deliver events. Use [ngrok](https://ngrok.com/)
or [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
ngrok http 7777
# or: cloudflared tunnel --url http://localhost:7777
```

Copy the public HTTPS URL and paste it into the Event Subscriptions Request URL
(step 4.3). The free ngrok tier gives you a random subdomain that changes on
restart — update the Request URL each time.

### 7. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/basic.py
```

DM the bot or @mention it in a channel to test.

## Examples

### Getting Started

- `basic.py` — Minimal agent that responds to @mentions with session history.
- `basic_workflow.py` — Two-step research-then-write workflow.

### Streaming

Streaming is enabled by default. Tokens arrive in real-time and tool calls
render as progress cards in Slack's plan display.

- `streaming_deep_research.py` — Deep research agent with 7 toolkits.
- `reasoning_agent.py` — Agent with step-by-step reasoning display.

### Teams and Workflows

- `support_team.py` — Support team routing to Technical Support or Documentation Specialist.
- `multimodal_team.py` — Team with GPT-4o vision input and DALL-E image output.
- `multimodal_workflow.py` — Parallel visual analysis + web research, then creative synthesis.

### Tools and Features

- `agent_with_user_memory.py` — Agent with MemoryManager that learns about users.
- `channel_summarizer.py` — Agent that reads channel history and summarizes threads.
- `file_analyst.py` — Agent that downloads, analyzes, and uploads files.
- `research_assistant.py` — Agent combining Slack search with web search.
- `multi_bot.py` — Multiple bots with different models in one server.
- `multiple_instances.py` — Two bots on one server with separate credentials.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bot doesn't respond | Event URL not set or server not running | Check Event Subscriptions shows "Verified" |
| `internal_error` on `chat.appendStream` | "Agents & AI Apps" not enabled, or missing `assistant:write` scope, or app not reinstalled after config changes | 1. Enable "Agents & AI Apps" (step 2). 2. Add `assistant:write` scope (step 3). 3. Reinstall the app to the workspace. |
| Blank streaming bubble | Wrong `recipient_user_id` | Ensure you're using the human user's ID, not the bot's |
| No plan-mode task cards | `slack_sdk` older than 3.40.0 | Run `pip install "slack_sdk>=3.40.0"` |
| No suggested prompts | `assistant_thread_started` event missing | Add it in Event Subscriptions (step 4) |
| Bot only responds to DMs, not channels | Missing `message.channels` event | Add channel events in Event Subscriptions |
| `SLACK_SIGNING_SECRET is not set` | Missing env var | Export `SLACK_SIGNING_SECRET` before running |
| 403 on event webhook | Invalid signing secret | Check the secret matches Basic Information page |
| URL verification fails | Server not running or wrong signing secret | Start the server (step 7) before setting the Request URL |
