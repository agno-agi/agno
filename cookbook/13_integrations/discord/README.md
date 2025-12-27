# Discord Client for Agno

This module provides a Discord client implementation for Agno, allowing you to create AI-powered Discord bots using Agno's agent framework.

## Prerequisites

Before you can use the Discord client, you'll need:

1. Python 3.8 or higher
2. A Discord bot token
3. Required Python packages:
   - discord.py
   - agno

## Installation

1. Install the required packages:
```bash
pip install discord.py agno
```

2. Create a Discord bot:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application" and give it a name
   - Go to the "Bot" section and click "Add Bot"
   - Under the bot settings, enable the following Privileged Gateway Intents:
     - Presence Intent
     - Server Members Intent
     - Message Content Intent
   - Copy your bot token (you'll need this later)

3. Set up your environment:
   - Create a `.envrc` file in your project root
   - Add your Discord bot token:
   ```
   DISCORD_TOKEN=your_bot_token_here
   ```

4. Invite Your Bot to Your Discord Server:
   - In your application's settings under **"OAuth2"** > **"URL Generator"**, select the `bot` scope
   - Under **"Bot Permissions"**, select the permissions your bot needs (e.g., sending messages)
   - Copy the generated URL, navigate to it in your browser, and select the server where you want to add the bot

## Usage

Here's a basic example of how to use the DiscordClient:

```python
from agno.agent import Agent
from agno.integrations.discord import DiscordClient
from agno.models.anthropic import Claude

# Create your agent
agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    instructions=["Your agent instructions here"],
    # Add other agent configurations as needed
)
# Initialize the Discord client
discord_agent = DiscordClient(media_agent)
if __name__ == "__main__":
    discord_agent.serve()
```

## Features

- Seamless integration with Agno's agent framework
- Support for all Discord bot features through discord.py
- Easy to extend and customize

## Configuration

The DiscordClient accepts the following parameters:

- `agent`: An Agno Agent instance that will handle the bot's responses
- Additional discord.py client parameters can be passed as keyword arguments

## Security Notes

- Never commit your Discord bot token to version control
- Always use environment variables or secure configuration management for sensitive data
- Make sure to set appropriate permissions for your bot in the Discord Developer Portal

## Support

If you encounter any issues or have questions, please:
1. Check the [Agno documentation](https://docs.agno.com)
2. Open an issue on the Agno GitHub repository
3. Join the Agno Discord server for community support
