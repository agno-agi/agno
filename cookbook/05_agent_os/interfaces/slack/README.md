# Slack Interface

Connect Agno agents and teams to Slack via the `Slack` interface.

## Examples

| Example | Description |
|---------|-------------|
| `basic.py` | Minimal agent with Slack interface |
| `reasoning_agent.py` | Claude agent that shows its reasoning |
| `file_analyst.py` | Analyzes files shared in Slack (CSV, JSON, code) |
| `channel_summarizer.py` | Summarizes channel activity and threads |
| `research_assistant.py` | Searches Slack and the web for information |
| `support_team.py` | Team of agents that routes questions to specialists |
| `agent_with_user_memory.py` | Agent that remembers user preferences |
| `basic_workflow.py` | Workflow-based Slack bot |
| `multiple_instances.py` | Multiple agents on one AgentOS |

## Setup

### 1. Create a Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" > "From scratch"
3. Name your app and select a workspace

### 2. Configure Bot Token Scopes

Go to "OAuth & Permissions" and add these **Bot Token Scopes**:

**Required for all examples:**
- `app_mentions:read`
- `chat:write`
- `im:history`
- `im:read`
- `im:write`

**For file handling** (`file_analyst.py`):
- `files:read`
- `files:write`

**For channel history** (`channel_summarizer.py`):
- `channels:history`
- `channels:read`

**For user info** (`research_assistant.py`, `support_team.py`):
- `users:read`

> **Note:** `search:read` requires a **user token** (`xoxp-...`), not a bot token.
> Bot tokens will get `not_allowed_token_type` errors for search. If using `search_messages`,
> set `SLACK_TOKEN` to a user token obtained via OAuth with user token scopes.

### 3. Install to Workspace

Go to "Install App" > "Install to Workspace" > Authorize. Repeat after changing scopes.

### 4. Subscribe to Events

Go to "Event Subscriptions" > Enable > add your Request URL (see step 6), then subscribe to:
- `app_mention`
- `message.im`
- `message.channels`
- `message.groups`

### 5. Enable Direct Messages

Go to "App Home" > "Show Tabs" > check "Allow users to send Slash commands and messages from the messages tab".

### 6. Environment Variables

```bash
export SLACK_TOKEN="xoxb-your-bot-token"
export SLACK_SIGNING_SECRET="your-signing-secret"
```

Find these in your Slack App settings:
- Bot token: "OAuth & Permissions"
- Signing secret: "Basic Information" > "App Credentials"

### 7. Run with ngrok

```bash
ngrok http --url=your-url.ngrok-free.app 8000
```

Then run your example:

```bash
python cookbook/05_agent_os/interfaces/slack/basic.py
```

Set the Request URL in Event Subscriptions to: `https://your-url.ngrok-free.app/slack/events`

## Troubleshooting

- **Events not received:** Verify ngrok URL, check app is installed, ensure bot is invited to the channel
- **File uploads failing:** Add `files:read` and `files:write` scopes, reinstall app
- **Search not working:** `search:read` needs a user token (`xoxp-...`), not a bot token
- **Signature verification failing:** Check `SLACK_SIGNING_SECRET` matches your app's signing secret
