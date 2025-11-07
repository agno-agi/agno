from agno.agent import Agent
from agno.integrations.discord import DiscordClient
from agno.models.google import Gemini

media_agent = Agent(
    name="Media Agent",
    model=Gemini(id="gemini-2.0-flash"),
    description="A Media processing agent",
    instructions="Analyze images, audios and videos sent by the user",
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

discord_agent = DiscordClient(media_agent)

if __name__ == "__main__":
    discord_agent.serve()
