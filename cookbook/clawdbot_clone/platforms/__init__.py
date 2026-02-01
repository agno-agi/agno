"""
Platform integrations for Clawdbot Clone.

Supports Discord, Telegram, Slack, and CLI interfaces.
"""

from .cli import run_cli
from .discord_bot import run_discord_bot

__all__ = ["run_discord_bot", "run_cli"]
