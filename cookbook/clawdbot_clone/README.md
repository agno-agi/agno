# Clawdbot Clone

A feature-complete clone of [Clawdbot](https://clawd.bot/), the viral personal AI assistant, built entirely with the Agno framework.

## What is Clawdbot?

Clawdbot is an open-source personal AI assistant created by Peter Steinberger that went viral with 60k+ GitHub stars. It's essentially "Claude with hands" - an AI that:

- **Remembers everything** - Persistent memory across sessions
- **Works everywhere** - Discord, Telegram, Slack, WhatsApp
- **Controls your computer** - Shell commands, file access, code execution
- **Reaches out to you** - Morning briefings, reminders, proactive alerts
- **Respects privacy** - Can run fully local with Ollama

This implementation recreates all core features using Agno.

## Quick Start

### 1. Basic CLI Chat

```bash
.venvs/demo/bin/python cookbook/clawdbot_clone/examples/01_basic_cli.py
```

### 2. Discord Bot

```bash
export DISCORD_BOT_TOKEN="your-token-here"
.venvs/demo/bin/python cookbook/clawdbot_clone/examples/02_discord_bot.py
```

### 3. With Computer Control

```bash
.venvs/demo/bin/python cookbook/clawdbot_clone/examples/03_with_tools.py
```

### 4. Proactive Features

```bash
.venvs/demo/bin/python cookbook/clawdbot_clone/examples/04_proactive.py
```

### 5. Local/Private Mode (Ollama)

```bash
# First: ollama pull llama3.2
.venvs/demo/bin/python cookbook/clawdbot_clone/examples/05_local_ollama.py
```

## Features

### Persistent Memory

The agent remembers everything about each user across sessions:

```python
from clawdbot_clone import create_clawdbot

agent = create_clawdbot()

# First conversation
agent.run("My name is Alex and I love hiking", user_id="alex")

# Later conversation - agent remembers!
agent.run("What do you know about me?", user_id="alex")
# -> "You're Alex, and you love hiking!"
```

### Multi-Platform Support

Run the same agent on multiple platforms with unified memory:

```python
from clawdbot_clone import create_clawdbot
from agno.integrations.discord import DiscordClient

agent = create_clawdbot()

# Discord
discord_bot = DiscordClient(agent)
discord_bot.serve()
```

### Computer Control

The agent can execute commands and access files:

```python
from clawdbot_clone import ClawdbotConfig, create_clawdbot

config = ClawdbotConfig(
    enable_shell=True,
    enable_file_access=True,
    enable_python=True,
    require_confirmation_for_shell=True,  # Safety first!
)

agent = create_clawdbot(config)
agent.run("List all Python files in the current directory")
```

### Proactive Capabilities

Schedule reminders and automated tasks:

```python
from clawdbot_clone.proactive import ProactiveScheduler, Reminder

scheduler = ProactiveScheduler(agent)

# Morning briefing at 8am
scheduler.add_morning_briefing(briefing_time=time(8, 0))

# Custom reminder
scheduler.add_reminder(Reminder(
    user_id="alex",
    message="Time for your standup meeting!",
    remind_at=datetime.now() + timedelta(hours=1),
))

scheduler.start()
```

### Privacy-First with Ollama

Run completely offline with local models:

```python
from clawdbot_clone import ClawdbotConfig, create_clawdbot

config = ClawdbotConfig(
    model_provider="ollama",
    model_id="llama3.2",
    enable_web_search=False,  # Fully offline
)

agent = create_clawdbot(config)
```

## Configuration

All settings can be configured via environment variables or the `ClawdbotConfig` class:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAWDBOT_BOT_NAME` | Jarvis | Name of your assistant |
| `CLAWDBOT_MODEL_PROVIDER` | anthropic | Model provider (anthropic, openai, google, ollama) |
| `CLAWDBOT_MODEL_ID` | claude-sonnet-4-20250514 | Model ID |
| `CLAWDBOT_DATABASE_URL` | postgresql://... | PostgreSQL URL |
| `CLAWDBOT_USE_SQLITE` | false | Use SQLite instead |
| `CLAWDBOT_ENABLE_SHELL` | true | Allow shell commands |
| `CLAWDBOT_ENABLE_FILE_ACCESS` | true | Allow file operations |
| `CLAWDBOT_ENABLE_PYTHON` | true | Allow Python execution |
| `DISCORD_BOT_TOKEN` | - | Discord bot token |

## Project Structure

```
clawdbot_clone/
├── __init__.py           # Main exports
├── config.py             # Configuration management
├── agent.py              # Core agent creation
├── platforms/
│   ├── cli.py            # CLI interface
│   └── discord_bot.py    # Discord integration
├── proactive/
│   └── scheduler.py      # Scheduled tasks & reminders
└── examples/
    ├── 01_basic_cli.py
    ├── 02_discord_bot.py
    ├── 03_with_tools.py
    ├── 04_proactive.py
    └── 05_local_ollama.py
```

## How It Works

This clone leverages Agno's built-in capabilities:

1. **Memory**: Agno's `enable_agentic_memory` automatically extracts and stores important information from conversations
2. **Multi-user**: Each Discord/Telegram user gets isolated memory via `user_id`
3. **Sessions**: Conversations are tracked per thread/channel via `session_id`
4. **Tools**: Agno's `ShellTools`, `FileTools`, `PythonTools` provide computer control
5. **Safety**: Human-in-the-loop confirmation for dangerous operations
6. **Platforms**: `DiscordClient` handles all Discord integration automatically

## Extending

### Add Custom Tools

```python
from agno.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    # Your implementation
    return f"Weather in {city}: Sunny, 72F"

agent = create_clawdbot()
agent.tools.append(get_weather)
```

### Add New Platforms

The agent works with any Agno integration:

```python
from agno.integrations.slack import SlackClient  # If available

agent = create_clawdbot()
slack_bot = SlackClient(agent)
slack_bot.serve()
```

## Comparison with Original Clawdbot

| Feature | Original Clawdbot | Agno Clone |
|---------|------------------|------------|
| Persistent Memory | Yes | Yes (via Agno) |
| Discord Support | Yes | Yes |
| Telegram Support | Yes | Extensible |
| WhatsApp Support | Yes | Via WhatsAppTools |
| Slack Support | Yes | Extensible |
| Computer Control | Yes | Yes |
| Proactive Messages | Yes | Yes |
| Local/Ollama | Yes | Yes |
| Open Source | Yes | Yes |

## Resources

- [Agno Documentation](https://docs.agno.com)
- [Original Clawdbot](https://clawd.bot/)
- [Clawdbot GitHub](https://github.com/steipete/clawdbot)

---

Built with [Agno](https://agno.com) - The framework for building AI agents.
