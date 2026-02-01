"""
Discord Bot Platform for Clawdbot Clone.

Run your personal AI assistant on Discord with persistent memory
and computer control capabilities.
"""

from typing import Optional

from agno.integrations.discord import DiscordClient

from ..agent import create_clawdbot
from ..config import ClawdbotConfig, get_config


def run_discord_bot(config: Optional[ClawdbotConfig] = None) -> None:
    """
    Run the Clawdbot as a Discord bot.

    The bot will:
    - Respond to messages in threads or DMs
    - Remember each user separately (per Discord user ID)
    - Track conversations per thread (session ID)
    - Support media attachments (images, files)
    - Require confirmation for dangerous operations (HITL)

    Args:
        config: Configuration object. If None, loads from environment.

    Environment Variables Required:
        DISCORD_BOT_TOKEN: Your Discord bot token
        CLAWDBOT_DATABASE_URL: PostgreSQL connection string (or use SQLite)

    Usage:
        1. Create a Discord application at https://discord.com/developers
        2. Create a bot and get the token
        3. Invite the bot to your server with appropriate permissions
        4. Set DISCORD_BOT_TOKEN environment variable
        5. Run this script

    Example:
        ```python
        from clawdbot_clone.platforms import run_discord_bot
        run_discord_bot()
        ```
    """
    if config is None:
        config = get_config()

    # Create the agent
    agent = create_clawdbot(config)

    # Wrap in Discord client
    discord_client = DiscordClient(agent)

    print(f"Starting {config.bot_name} on Discord...")
    print("Bot is ready! Send a message to start chatting.")

    # Start the bot (blocks until shutdown)
    discord_client.serve()


def create_discord_client(config: Optional[ClawdbotConfig] = None) -> DiscordClient:
    """
    Create a Discord client without starting it.

    Useful for custom setups or testing.

    Args:
        config: Configuration object.

    Returns:
        DiscordClient instance ready to be started.
    """
    if config is None:
        config = get_config()

    agent = create_clawdbot(config)
    return DiscordClient(agent)


if __name__ == "__main__":
    run_discord_bot()
