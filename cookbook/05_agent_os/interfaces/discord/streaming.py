"""
Streaming
=========

Discord bot with streaming enabled — the response message is progressively
updated as the model generates content, so users see text appear in real time.

Prerequisites:
    export DISCORD_BOT_TOKEN="your-bot-token"
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export OPENAI_API_KEY="your-openai-key"

Run:
    python cookbook/05_agent_os/interfaces/discord/streaming.py

Then expose via ngrok:
    ngrok http 7777

Set the Interactions Endpoint URL in the Discord Developer Portal to:
    https://<ngrok-url>/discord/interactions
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/discord_streaming.db")

streaming_agent = Agent(
    name="Streaming Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[streaming_agent],
    interfaces=[
        Discord(
            agent=streaming_agent,
            stream=True,
            reply_in_thread=True,
        )
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="streaming:app", reload=True)
