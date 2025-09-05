from agno.agent import Agent
from agno.integrations.discord import DiscordClient
from agno.models.openai import OpenAIChat

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

discord_agent = DiscordClient(basic_agent)

if __name__ == "__main__":
    discord_agent.serve()
