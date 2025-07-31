import os

from agno.agent import Agent
from agno.tools.discord import DiscordTools

# Get Discord token from environment
discord_token = os.getenv("DISCORD_BOT_TOKEN")
if not discord_token:
    raise ValueError("DISCORD_BOT_TOKEN not set")

# Initialize Discord tools
discord_tools = DiscordTools(
    bot_token=discord_token,
    enable_messaging=True,
    enable_history=True,
    enable_channel_management=True,
    enable_message_management=True,
)

# Create an agent with Discord tools
discord_agent = Agent(
    name="Discord Agent",
    instructions=[
        "You are a Discord bot that can perform various operations.",
        "You can send messages, read message history, manage channels, and delete messages.",
    ],
    tools=[discord_tools],
    show_tool_calls=True,
    markdown=True,
)

# Replace with your Discord IDs
channel_id = "YOUR_CHANNEL_ID"
server_id = "YOUR_SERVER_ID"

# Example 1: Send a message
discord_agent.print_response(
    f"Send a message 'Hello from Agno!' to channel {channel_id}", stream=True
)

# Example 2: Get channel info
discord_agent.print_response(f"Get information about channel {channel_id}", stream=True)

# Example 3: List channels
discord_agent.print_response(f"List all channels in server {server_id}", stream=True)

# Example 4: Get message history
discord_agent.print_response(
    f"Get the last 5 messages from channel {channel_id}", stream=True
)

# Example 5: Delete a message (replace message_id with an actual message ID)
# message_id = 123456789
# discord_agent.print_response(
#     f"Delete message {message_id} from channel {channel_id}",
#     stream=True
# )
