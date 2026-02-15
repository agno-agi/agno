# Discord Cookbook

Examples for `interfaces/discord` in AgentOS.

## Files
- `basic.py` — Basic agent with conversation history.
- `reasoning_agent.py` — Agent with reasoning tools and web search.
- `agent_with_media.py` — Agent with DALL-E image generation and ElevenLabs TTS.
- `support_team.py` — Multi-agent support team.

## Prerequisites

1. Create a Discord Application at https://discord.com/developers/applications
2. Enable the Bot in your application and copy the bot token
3. Set environment variables:
   ```bash
   export DISCORD_BOT_TOKEN="your-bot-token"
   export DISCORD_PUBLIC_KEY="your-public-key"
   export DISCORD_APPLICATION_ID="your-app-id"
   ```
4. Run examples with `.venvs/demo/bin/python <path-to-file>.py`
5. Expose via ngrok: `ngrok http 7777`
6. Set the Interactions Endpoint URL in the Developer Portal to `https://<ngrok-url>/discord/interactions`
7. Invite the bot to your server with the `applications.commands` and `bot` scopes

## Transports

Discord uses two transports:

- **HTTP (slash commands)** — Handles `/ask` commands via webhook POST requests. Works with any hosting setup that exposes an HTTPS endpoint.
- **Gateway (WebSocket)** — Handles @mention messages via a persistent WebSocket connection. Auto-activates when `discord.py` is installed and `DISCORD_BOT_TOKEN` is set.

Both transports work simultaneously when the Gateway is available.
