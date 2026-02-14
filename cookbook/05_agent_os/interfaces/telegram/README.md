# Telegram Interface

Connect your Agno agents to Telegram as a bot with full media support.

## Overview

The Telegram interface lets you serve an Agno Agent, Team, or Workflow as a Telegram bot. It handles inbound messages (text, photos, voice, video, documents), runs them through your agent, and sends back text or media responses. Built on FastAPI with webhook-based message delivery.

## Prerequisites

- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A model API key (examples use Google Gemini or OpenAI)
- [ngrok](https://ngrok.com/) for local development (exposes localhost to the internet)

## Getting Started

### 1. Install dependencies

If using the demo virtual environment (recommended):

```bash
./scripts/demo_setup.sh
```

Or install manually:

```bash
pip install 'agno[telegram]'
```

### 2. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 3. Set environment variables

```bash
export TELEGRAM_TOKEN="your-bot-token-from-botfather"
export GOOGLE_API_KEY="your-google-api-key"       # For Gemini examples
export APP_ENV="development"                        # Bypasses webhook secret validation
```

The `APP_ENV=development` setting is important for local testing. Without it, the server runs in production mode and requires a `TELEGRAM_WEBHOOK_SECRET_TOKEN`, returning 403 errors on every webhook request.

### 4. Run the bot

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/basic_agent.py
```

The server starts on `http://localhost:7777`.

### 5. Expose with ngrok

In a separate terminal:

```bash
ngrok http 7777
```

Copy the `https://` forwarding URL (e.g., `https://abc123.ngrok-free.app`).

### 6. Set the webhook

Tell Telegram to send updates to your ngrok URL:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook?url=https://YOUR-NGROK-URL/telegram/webhook"
```

You should see `{"ok":true,"result":true,"description":"Webhook was set"}`.

### 7. Verify it works

Open your bot in Telegram and send `/start` or any message. You should see:
- A "typing..." indicator in the chat
- A response from your agent within a few seconds
- Server logs showing `Processing message from <user_id>: <message>`

## Examples

| File | Model | Description |
|------|-------|-------------|
| `basic.py` | OpenAI `gpt-4o` | Minimal setup with conversation history |
| `basic_agent.py` | Gemini `gemini-2.5-pro` | Basic agent with group chat mention filtering |
| `agent_with_user_memory.py` | Gemini `gemini-2.0-flash` | Remembers user preferences across sessions using MemoryManager |
| `agent_with_media.py` | Gemini + DALL-E + ElevenLabs | Generates images and audio, analyzes inbound media |
| `reasoning_agent.py` | Claude `claude-3-7-sonnet` | Uses ReasoningTools and DuckDuckGo for research |
| `multiple_instances.py` | OpenAI `gpt-5.2` | Two bots on one server with separate webhook paths (`/basic`, `/web-research`) |

Run any example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/<filename>.py
```

## Group Chat Support

By default, the bot only responds when mentioned (`@your_bot`) or replied to in group chats. This is controlled by the `reply_to_mentions_only` flag:

```python
Telegram(
    agent=my_agent,
    reply_to_mentions_only=True,   # Default: only respond to @mentions and replies
    reply_to_bot_messages=True,    # Default: also respond when users reply to the bot's messages
)
```

To have the bot respond to all messages in a group, set `reply_to_mentions_only=False`.

**BotFather privacy mode:** By default, Telegram bots in groups only receive messages that mention them or are commands. If you want the bot to see all group messages (for `reply_to_mentions_only=False`), message @BotFather, send `/setprivacy`, select your bot, and choose **Disable**.

## Features

- Text messages with conversation history
- Inbound media: photos, stickers, voice notes, audio, video, video notes, animations, documents
- Outbound media: images, audio, video, files from agent responses (URL, bytes, or filepath)
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

- Telegram requires HTTPS for webhook URLs. Use a reverse proxy (nginx, Caddy) with TLS in production.
- The server runs on port 7777 by default via AgentOS.

## Troubleshooting

**403 errors on webhook requests:**
You're running in production mode without a webhook secret. Either set `APP_ENV=development` for local testing, or set `TELEGRAM_WEBHOOK_SECRET_TOKEN` and register the webhook with the matching `secret_token`.

**"Bad Request: invalid file_id" when sending media:**
This happens when the bot receives a file_id from a different bot token or an expired file. File IDs are scoped to a specific bot token. Re-send the media to get a fresh file_id.

**"Bad Request: message to be replied not found":**
The bot tried to reply to a message that was deleted or is in a different chat. This can happen in group chats when messages are deleted before the bot responds. The bot will fall back to sending without a reply.

**No response from the bot:**
1. Check that the server is running (`curl http://localhost:7777/telegram/status`)
2. Verify ngrok is forwarding (`curl https://YOUR-NGROK-URL/telegram/status`)
3. Confirm the webhook is set (`curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"`)
4. Check server logs for error messages
