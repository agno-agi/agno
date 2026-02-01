"""
Clawdbot Clone - A Personal AI Assistant built with Agno

This is a feature-complete clone of Clawdbot, the viral AI assistant,
built entirely using the Agno framework.

Features:
- Persistent memory across sessions (remembers everything about you)
- Multi-platform support (Discord, CLI, extensible to Telegram/Slack)
- Computer control (shell commands, file access, Python execution)
- Web search and browser control
- Proactive capabilities (scheduled tasks, reminders, briefings)
- Privacy-first (can run with local Ollama models)

Quick Start:
    ```python
    from clawdbot_clone import quick_start

    # Start chatting in the CLI
    bot = quick_start(name="Jarvis")
    bot.print_response("Hello! What can you help me with?")
    ```

Discord Bot:
    ```python
    from clawdbot_clone.platforms import run_discord_bot
    run_discord_bot()  # Requires DISCORD_BOT_TOKEN env var
    ```

CLI Mode:
    ```python
    from clawdbot_clone.platforms import run_cli
    run_cli()
    ```
"""

from .agent import create_clawdbot, quick_start
from .config import ClawdbotConfig, get_config

__all__ = [
    "create_clawdbot",
    "quick_start",
    "ClawdbotConfig",
    "get_config",
]

__version__ = "0.1.0"
