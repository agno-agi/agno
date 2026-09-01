"""
Discord Bot
Run an Agno agent as a Discord bot with DiscordClient.

Prerequisites: OPENAI_API_KEY, DISCORD_BOT_TOKEN, and a Discord bot with
message-content intent and thread permissions enabled.
Run: .venvs/demo/bin/python cookbook/integrations/discord/basic.py
Try: Send the bot a direct message or mention it in a server channel.
"""

import discord
from agno.agent import Agent
from agno.integrations.discord import DiscordClient
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Discord Bot
# ---------------------------------------------------------------------------

discord_assistant = Agent(
    name="Discord Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    add_history_to_context=True,
    num_history_runs=3,
)

discord_intents = discord.Intents.default()
discord_intents.message_content = True
discord_bot = discord.Client(intents=discord_intents)
discord_client = DiscordClient(agent=discord_assistant, client=discord_bot)


# ---------------------------------------------------------------------------
# Run Discord Bot
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    discord_client.serve()
