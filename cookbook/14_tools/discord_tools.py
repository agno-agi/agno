import os

from agno.agent import Agent
from agno.tools.discord import DiscordTools

# Get Discord token from environment
discord_token = os.getenv("DISCORD_BOT_TOKEN")
if not discord_token:
    raise ValueError("DISCORD_BOT_TOKEN not set")

# Example 1: Enable all Discord functions
discord_agent_all = Agent(
    name="Discord Agent - All Functions",
    instructions=[
        "You are a Discord bot with access to all Discord operations.",
        "You can send messages, manage channels, read history, and manage messages.",
    ],
    tools=[
        DiscordTools(
            bot_token=discord_token,
            all=True,  # Enable all Discord functions
        )
    ],
    markdown=True,
)

# Example 2: Enable specific Discord functions only
discord_agent_specific = Agent(
    name="Discord Agent - Specific Functions",
    instructions=[
        "You are a Discord bot with limited operations.",
        "You can only send messages and read message history.",
    ],
    tools=[
        DiscordTools(
            bot_token=discord_token,
            enable_send_message=True,
            enable_get_channel_messages=True,
            enable_get_channel_info=False,
            enable_list_channels=False,
            enable_delete_message=False,
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with specific configurations
discord_agent = Agent(
    name="Discord Agent - Default",
    instructions=[
        "You are a Discord bot that can perform various operations.",
        "You can send messages, read message history, manage channels, and delete messages.",
    ],
    tools=[
        DiscordTools(
            bot_token=discord_token,
            enable_send_message=True,
            enable_get_channel_messages=True,
            enable_get_channel_info=True,
            enable_list_channels=True,
            enable_delete_message=True,
        )
    ],
    markdown=True,
)

# Replace with your Discord IDs
channel_id = "YOUR_CHANNEL_ID"
server_id = "YOUR_SERVER_ID"

# Example usage with all functions enabled
print("=== Example 1: Using all Discord functions ===")
discord_agent_all.print_response(
    f"Send a message 'Hello from Agno with all functions!' to channel {channel_id}",
    stream=True,
)

# Example usage with specific functions only
print("\n=== Example 2: Using specific Discord functions ===")
discord_agent_specific.print_response(
    f"Send a message 'Hello from limited bot!' to channel {channel_id}", stream=True
)

# Example usage with default configuration
print("\n=== Example 3: Default Discord agent usage ===")
discord_agent.print_response(
    f"Send a message 'Hello from Agno!' to channel {channel_id}", stream=True
)

discord_agent.print_response(f"Get information about channel {channel_id}", stream=True)

discord_agent.print_response(f"List all channels in server {server_id}", stream=True)

discord_agent.print_response(
    f"Get the last 5 messages from channel {channel_id}", stream=True
)

# Example: Delete a message (replace message_id with an actual message ID)
# message_id = 123456789
# discord_agent.print_response(
#     f"Delete message {message_id} from channel {channel_id}",
#     stream=True
# )
