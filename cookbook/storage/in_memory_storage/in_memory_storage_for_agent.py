"""Run `pip install ddgs openai` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.in_memory import InMemoryStorage
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=InMemoryStorage(),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
