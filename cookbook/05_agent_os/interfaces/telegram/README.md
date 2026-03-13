# Telegram Cookbook

Examples for connecting Agno agents, teams, and workflows to Telegram using the
`Telegram` interface in AgentOS. Supports text, media, streaming, and multi-agent
teams via Telegram's Bot API with webhook-based message delivery.

## Telegram Bot Setup

Follow these steps to create and configure a Telegram bot for use with Agno.

### 1. Create the Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts to choose a display name and username
   (username must end in `bot`, e.g. `my_agno_bot`).
3. Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`).

Optional BotFather commands to polish your bot:

| Command | Purpose |
|---------|---------|
| `/setdescription` | Bio shown on the bot's profile page |
| `/setabouttext` | Short description in the chat list |
| `/setcommands` | Register slash commands so users see a `/` menu |
| `/setuserpic` | Set the bot's avatar |
| `/setprivacy` | Toggle group privacy mode (see Group Chat Support below) |

### 2. Set Environment Variables

```bash
export TELEGRAM_TOKEN="your-bot-token-from-botfather"
export GOOGLE_API_KEY="your-google-api-key"       # For Gemini examples
export APP_ENV="development"                        # Bypasses webhook secret validation
```

The `APP_ENV=development` setting is important for local testing. Without it, the
server runs in production mode and requires a `TELEGRAM_WEBHOOK_SECRET_TOKEN`,
returning 403 errors on every webhook request.

### 3. Start a Tunnel

Telegram needs a public HTTPS URL to deliver webhook events. Use
[ngrok](https://ngrok.com/) or
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
ngrok http 7777
# or: cloudflared tunnel --url http://localhost:7777
```

Copy the public HTTPS URL (e.g. `https://abc123.ngrok-free.app`). The free ngrok
tier gives you a random subdomain that changes on restart.

### 4. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/basic.py
```

The server starts on `http://localhost:7777`.

### 5. Set the Webhook

Tell Telegram to send updates to your tunnel URL:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook?url=https://YOUR-NGROK-URL/telegram/webhook"
```

You should see `{"ok":true,"result":true,"description":"Webhook was set"}`.

> Verify anytime with: `curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"`

### 6. Verify It Works

Open your bot in Telegram and send `/start` or any message. You should see:
- A "typing..." indicator in the chat
- A response from your agent within a few seconds
- Server logs showing `Processing message from <user_id>: <message>`

## Examples

### Getting Started

- `basic.py` -- Minimal agent with conversation history and group chat mention filtering (Gemini).
- `workflow.py` -- Two-step draft-and-edit workflow where a Drafter writes and an Editor polishes.

### Streaming

Streaming is opt-in via `streaming=True` on the Telegram interface. Tokens arrive
in real-time by editing the message progressively, so the user sees incremental
output instead of waiting for the full response.

- `streaming.py` -- Token-by-token streaming with live message edits (OpenAI).
- `streaming_workflow.py` -- Two-step research-and-write workflow with real-time step progress.

### Teams and Workflows

- `team.py` -- Multi-agent team with a Researcher and a Writer, coordinated by a team leader.
- `workflow.py` -- Sequential draft-and-edit workflow with two specialized agents.
- `streaming_workflow.py` -- Streaming variant of the research workflow with live status updates.

### Tools and Features

- `agent_with_user_memory.py` -- Agent with MemoryManager that learns and remembers user preferences.
- `agent_with_media.py` -- Multimedia bot with DALL-E image generation, ElevenLabs audio, and inbound media analysis.
- `reasoning_agent.py` -- Claude agent with chain-of-thought reasoning and DuckDuckGo search.
- `multiple_instances.py` -- Two agents behind one bot on separate webhook paths (`/basic`, `/web-research`).

Run any example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/<filename>.py
```

## Group Chat Support

By default, the bot only responds when mentioned (`@your_bot`) or replied to in
group chats. This is controlled by the `reply_to_mentions_only` flag:

```python
Telegram(
    agent=my_agent,
    reply_to_mentions_only=True,   # Default: only respond to @mentions and replies
    reply_to_bot_messages=True,    # Default: also respond when users reply to the bot's messages
)
```

To have the bot respond to all messages in a group, set `reply_to_mentions_only=False`.

**BotFather privacy mode:** By default, Telegram bots in groups only receive
messages that mention them or are commands. If you want the bot to see all group
messages (for `reply_to_mentions_only=False`), message @BotFather, send
`/setprivacy`, select your bot, and choose **Disable**.

## Features

- Text messages with conversation history
- Inbound media: photos, stickers, voice notes, audio, video, video notes, animations, documents
- Outbound media: images, audio, video, files from agent responses (URL, bytes, or filepath)
- Streaming responses with progressive message edits
- Typing indicators while processing
- Long message chunking (Telegram's 4096 character limit)
- Per-user session tracking (`tg:{chat_id}`)
- Group chat thread tracking (`tg:{chat_id}:thread:{message_id}`)
- Works with Agent, Team, and Workflow
- Webhook secret token validation in production
- Built-in `/start` and `/help` command handlers

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_TOKEN` | Yes | - | Bot token from BotFather |
| `GOOGLE_API_KEY` | Depends | - | Required for Gemini-based examples |
| `OPENAI_API_KEY` | Depends | - | Required for OpenAI/DALL-E-based examples |
| `ANTHROPIC_API_KEY` | Depends | - | Required for Claude-based examples |
| `APP_ENV` | No | (production mode) | Set to `development` to bypass webhook secret validation |
| `TELEGRAM_WEBHOOK_SECRET_TOKEN` | Production | - | Required when `APP_ENV` is not `development` |

## Production Notes

- When `APP_ENV` is not set to `development`, the server enforces webhook secret token validation. Set `TELEGRAM_WEBHOOK_SECRET_TOKEN` and include it when registering the webhook:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-domain.com/telegram/webhook",
    "secret_token": "your-secret-token"
  }'
```

- Telegram requires HTTPS for webhook URLs (ports 443, 80, 88, or 8443). Use a reverse proxy (nginx, Caddy) with TLS in production.
- The server runs on port 7777 by default via AgentOS.
- Rate limits: 30 messages/second globally, 1 message/second per chat, 20 messages/minute per group.
- File limits: bots can download files up to 20 MB and upload up to 50 MB.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| 403 errors on webhook requests | Running in production mode without a webhook secret | Set `APP_ENV=development` for local testing, or set `TELEGRAM_WEBHOOK_SECRET_TOKEN` and register the webhook with the matching `secret_token` |
| "Bad Request: invalid file_id" | File ID from a different bot token or expired | File IDs are scoped to a specific bot token -- re-send the media to get a fresh one |
| "message to be replied not found" | Original message was deleted before bot responded | Happens in group chats -- the bot logs the error and sends a fallback message |
| No response from the bot | Server not running or webhook not set | 1. Check server: `curl http://localhost:7777/telegram/status` 2. Check tunnel: `curl https://YOUR-NGROK-URL/telegram/status` 3. Check webhook: `curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"` |
| Bot ignores group messages | Privacy mode enabled (default) | Message @BotFather, send `/setprivacy`, select your bot, choose **Disable** |
| Blank or missing streaming edits | `streaming=True` not set on the Telegram interface | Pass `streaming=True` when creating the `Telegram` instance |
| `TELEGRAM_TOKEN is not set` | Missing env var | Export `TELEGRAM_TOKEN` before running |
