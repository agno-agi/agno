"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.langdb import LangDB
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=LangDB(id="llama3-1-70b-instruct-v1.0"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
