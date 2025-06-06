from agno.agent import Agent
from agno.app.discord.client import DiscordClient
from agno.models.openai import OpenAIChat

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
)

if __name__ == "__main__":
    DiscordClient(basic_agent)
