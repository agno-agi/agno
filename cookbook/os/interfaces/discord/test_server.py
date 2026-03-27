"""Quick test server for the Discord Interface.

Usage:
    export DISCORD_BOT_TOKEN="your-bot-token"
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export OPENAI_API_KEY="your-openai-key"  # or any model provider key

    python cookbook/os/interfaces/discord/test_server.py

Then expose via ngrok:
    ngrok http 8000

And set the Interactions Endpoint URL in the Discord Developer Portal to:
    https://<ngrok-url>/discord/interactions
"""

import uvicorn
from agno.agent import Agent
from agno.models.google import Gemini
from agno.os.interfaces.discord.discord import Discord
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.eleven_labs import ElevenLabsTools
from fastapi import FastAPI

# Create a simple agent
agent = Agent(
    name="Agno Discord Bot",
    model=Gemini(id="gemini-3-pro-preview"),
    instructions=["You are a helpful assistant on Discord. Keep responses concise."],
    tools=[
        DuckDuckGoTools(),
        DalleTools(),
        ElevenLabsTools(
            enable_text_to_speech=True,
            enable_generate_sound_effect=True,
            enable_get_voices=False,
        ),
    ],
    markdown=True,
)

# Create the Discord interface
discord = Discord(
    agent=agent,
    show_reasoning=True,
    max_message_chars=1900,
    reply_in_thread=False,
)

# Build FastAPI app — attach gateway lifespan so @mentions work via WebSocket
app = FastAPI(title="Agno Discord Bot", lifespan=discord.get_lifespan())
app.include_router(discord.get_router())


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    print("Starting Discord bot server on http://0.0.0.0:7777")
    print("Expose with: ngrok http 7777")
    print("Then set Interactions Endpoint URL to: https://<ngrok>/discord/interactions")
    uvicorn.run(app, host="0.0.0.0", port=8000)
