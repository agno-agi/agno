from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    add_datetime_to_context=True,
    timezone_identifier="Etc/UTC",
)
agent.print_response(
    "What is the current date and time? What is the current time in NYC?"
)
