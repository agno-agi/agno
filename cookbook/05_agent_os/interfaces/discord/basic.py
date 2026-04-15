"""
Basic Discord Bot
=================

Minimal Discord bot with slash command support and conversation history.

Prerequisites:
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export OPENAI_API_KEY="your-openai-key"

Run:
    python cookbook/05_agent_os/interfaces/discord/basic.py

Then expose via ngrok:
    ngrok http 7777

Set the Interactions Endpoint URL in the Discord Developer Portal to:
    https://<ngrok-url>/discord/interactions
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord

agent = Agent(
    name="Discord Bot",
    model=OpenAIResponses(id="gpt-4o-mini"),
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[
        Discord(
            agent=agent,
            streaming=True,
        )
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic:app", port=7777, reload=True)
