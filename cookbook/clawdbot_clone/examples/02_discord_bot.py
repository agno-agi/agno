"""
Discord Bot Example - Clawdbot Clone

Run your personal AI assistant on Discord with full memory
and computer control capabilities.

Setup:
    1. Create a Discord application at https://discord.com/developers
    2. Create a bot and copy the token
    3. Enable "Message Content Intent" in the bot settings
    4. Invite the bot to your server with these permissions:
       - Read Messages/View Channels
       - Send Messages
       - Create Public Threads
       - Send Messages in Threads
       - Read Message History

    5. Set the environment variable:
       export DISCORD_BOT_TOKEN="your-bot-token-here"

    6. Run this script:
       .venvs/demo/bin/python cookbook/clawdbot_clone/examples/02_discord_bot.py

Features:
    - Creates threads for each conversation
    - Remembers each user separately
    - Supports image/file attachments
    - Human-in-the-loop confirmation for dangerous operations
"""

import os
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cookbook.clawdbot_clone import ClawdbotConfig, create_clawdbot

from agno.integrations.discord import DiscordClient

# Check for token
if not os.getenv("DISCORD_BOT_TOKEN"):
    print("Error: DISCORD_BOT_TOKEN environment variable not set")
    print()
    print("To get a token:")
    print("  1. Go to https://discord.com/developers/applications")
    print("  2. Create a new application")
    print("  3. Go to Bot section and create a bot")
    print("  4. Copy the token and set it:")
    print("     export DISCORD_BOT_TOKEN='your-token-here'")
    sys.exit(1)

# Create configuration
config = ClawdbotConfig(
    bot_name="Jarvis",
    bot_personality="helpful, witty, and always ready to assist",
    # Use SQLite for easy setup, switch to PostgreSQL for production
    use_sqlite=True,
    sqlite_path="tmp/clawdbot_discord.db",
    # Enable all tools
    enable_shell=True,
    enable_file_access=True,
    enable_python=True,
    enable_web_search=True,
    enable_web_browser=True,
    # Safety: require confirmation for dangerous operations
    require_confirmation_for_shell=True,
    require_confirmation_for_file_write=True,
)

# Create the agent
agent = create_clawdbot(config)

# Wrap in Discord client
discord_client = DiscordClient(agent)

print("=" * 50)
print(f"Starting {config.bot_name} on Discord")
print("=" * 50)
print()
print("The bot is now running!")
print("Send a message in any channel or DM to start chatting.")
print()
print("Press Ctrl+C to stop the bot.")
print()

# Run the bot (blocks until shutdown)
discord_client.serve()
