from agno.agent import Agent
from agno.app.discord.client import DiscordClient
from agno.models.google import Gemini

media_agent = Agent(
    name="Media Agent",
    model=Gemini(id="gemini-2.0-flash"),
    add_history_to_messages=True, 
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

if __name__ == "__main__":
    DiscordClient(media_agent)