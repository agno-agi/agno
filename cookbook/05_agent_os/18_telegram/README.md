# Telegram

The `Telegram` interface connects an Agent, Team, or Workflow to Telegram's
Bot API through a webhook. This lesson focuses on the channel-specific
behavior: default-on streaming, group mention filtering, inbound and outbound
media, bot commands, quoted replies, and prefix routing for multiple bots.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Serve one persistent assistant with streaming and group mention filtering. |
| `media.py` | Receive multimodal messages and return generated images and audio. |
| `multiple_instances.py` | Mount two independently credentialed Telegram bots on separate prefixes. |

## Prerequisites

Install the demo environment:

```bash
./scripts/demo_setup.sh
```

The Telegram interface requires the `agno[telegram]` extra. Its `telebot`
import is supplied by the `pyTelegramBotAPI` package.

| File | Environment variables |
|---|---|
| `basic.py` | `TELEGRAM_TOKEN`, `OPENAI_API_KEY` |
| `media.py` | `TELEGRAM_TOKEN`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ELEVEN_LABS_API_KEY` |
| `multiple_instances.py` | `ASSISTANT_TELEGRAM_TOKEN`, `RESEARCH_TELEGRAM_TOKEN`, `OPENAI_API_KEY` |

For local webhook testing, set `APP_ENV=development` to bypass Telegram's
secret-token check. In production, set `TELEGRAM_WEBHOOK_SECRET_TOKEN` and
register the same value as the webhook's `secret_token`.

## Create and Connect a Bot

Create a bot with `@BotFather`, copy its token, and export it:

```bash
export TELEGRAM_TOKEN="your-bot-token"
export OPENAI_API_KEY="your-openai-key"
export APP_ENV="development"
```

Start the basic server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/18_telegram/basic.py
```

Telegram needs a public HTTPS callback. Expose port 7777 with a tunnel, then
register the default webhook:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://YOUR-PUBLIC-HOST/telegram/webhook"}'
```

The default interface mounts:

| Operation | Route |
|---|---|
| Status | `GET /telegram/status` |
| Incoming updates | `POST /telegram/webhook` |

AgentOS also exposes `GET /health` and `GET /config` on the same server.

## Run

Start one standalone example at a time:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/18_telegram/basic.py
.venvs/demo/bin/python cookbook/05_agent_os/18_telegram/media.py
.venvs/demo/bin/python cookbook/05_agent_os/18_telegram/multiple_instances.py
```

Each file uses port 7777 and the webhook prefixes listed in this README.

## Streaming and Group Chats

`streaming=True` is the interface default. Telegram progressively edits the
reply while the Agent runs, so a separate streaming example would only repeat
the basic configuration.

In direct messages, the bot processes normal messages. In groups,
`reply_to_mentions_only=True` means it responds only when mentioned or when a
user replies to one of its messages. `reply_to_bot_messages=True` enables the
reply case. Telegram's BotFather privacy setting still determines which group
messages Telegram delivers to the bot.

## Commands and Quoted Responses

The interface provides `/start`, `/help`, and `/new`. `/new` starts a fresh
session while preserving older sessions and therefore requires the Agent,
Team, or Workflow to have a database.

`commands` accepts menu entries such as:

```python
commands=[
    {"command": "start", "description": "Start the bot"},
    {"command": "help", "description": "Show help"},
    {"command": "new", "description": "Start a new conversation"},
]
```

With `register_commands=True`, which is the default, the menu is registered
lazily when the first message is processed. That operation contacts
Telegram's API and is not performed by construction smoke tests.

Set `quoted_responses=True` to reply directly to the incoming message in
private chats. Group responses already quote the triggering message.

Conversation sessions are scoped as
`tg:{entity_id}:{chat_id}`. Supergroup reply threads and forum topics append
the `message_thread_id`.

## Media

The interface downloads photos, static stickers, voice notes, audio, videos,
video notes, animations, and documents and passes them to the served entity as
Agno media objects. Telegram bot downloads are limited to 20 MB by this
interface.

Images, audio, video, and files returned by the Agent are sent back to the
chat automatically. `media.py` uses Gemini for inbound understanding,
DALL-E for image generation, and ElevenLabs for speech and sound effects.

## Multiple Bots and Prefixes

Telegram stores one webhook URL per bot. To run `multiple_instances.py`
honestly, create two bots and register each token against its own route:

```bash
curl -X POST \
  "https://api.telegram.org/bot${ASSISTANT_TELEGRAM_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://YOUR-PUBLIC-HOST/assistant/webhook"}'

curl -X POST \
  "https://api.telegram.org/bot${RESEARCH_TELEGRAM_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://YOUR-PUBLIC-HOST/research/webhook"}'
```

The mounted routes are:

| Bot | Status | Webhook |
|---|---|---|
| Assistant | `GET /assistant/status` | `POST /assistant/webhook` |
| Research | `GET /research/status` | `POST /research/webhook` |

The production webhook secret is global to this AgentOS process. Because it is
chosen by the operator, both bot registrations can use the same
`TELEGRAM_WEBHOOK_SECRET_TOKEN`.
