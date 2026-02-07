# Telegram Interface

Connect your Agno agents to Telegram as a bot.

## Prerequisites

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Save the bot token (e.g. `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Set Environment Variables

```bash
export TELEGRAM_TOKEN="your-bot-token"

# Optional: for production webhook security
export TELEGRAM_WEBHOOK_SECRET_TOKEN="your-secret-token"
```

### 3. Expose Your Local Server

Telegram sends webhook requests to a public URL. Use [ngrok](https://ngrok.com/) for local development:

```bash
ngrok http 7777
```

### 4. Set the Webhook URL

Tell Telegram where to send updates:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-ngrok-url.ngrok.io/telegram/webhook",
    "secret_token": "your-secret-token"
  }'
```

## Running Examples

```bash
# Basic agent
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/basic.py

# Agent with memory
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/agent_with_user_memory.py

# Media-capable agent (handles photos)
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/agent_with_media.py

# Finance agent with reasoning
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/reasoning_agent.py

# Multiple bots on one server
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/telegram/multiple_instances.py
```

## Features

- Text messages with conversation history
- Photo messages with captions (multimodal)
- Typing indicators while processing
- Long message splitting (Telegram 4096 char limit)
- Per-user session tracking (`tg:{chat_id}`)
- Webhook secret token validation in production
- Development mode bypasses security for local testing

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
| `TELEGRAM_WEBHOOK_SECRET_TOKEN` | Production | Secret for webhook validation |
| `APP_ENV` | No | Set to `production` to enforce webhook security (default: `development`) |

## Production Notes

- Set `APP_ENV=production` to enforce webhook secret token validation
- Use a reverse proxy (nginx, Caddy) with HTTPS
- Telegram requires HTTPS for webhook URLs
- Set the webhook with `secret_token` parameter for added security
