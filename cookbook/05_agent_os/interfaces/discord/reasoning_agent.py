"""
Reasoning Agent
===============

Discord bot with reasoning tools and web search.

Prerequisites:
    export DISCORD_BOT_TOKEN="your-bot-token"
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export ANTHROPIC_API_KEY="your-anthropic-key"

Run:
    python cookbook/05_agent_os/interfaces/discord/reasoning_agent.py

Then expose via ngrok:
    ngrok http 7777

Set the Interactions Endpoint URL in the Discord Developer Portal to:
    https://<ngrok-url>/discord/interactions
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic.claude import Claude
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/discord_reasoning.db")

reasoning_agent = Agent(
    name="Reasoning Agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    db=agent_db,
    tools=[
        ReasoningTools(add_instructions=True),
        DuckDuckGoTools(),
    ],
    instructions="Use tables to display data. When you use thinking tools, keep the thinking brief.",
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[reasoning_agent],
    interfaces=[
        Discord(
            agent=reasoning_agent,
            show_reasoning=True,
            reply_in_thread=True,
        )
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="reasoning_agent:app", reload=True)
