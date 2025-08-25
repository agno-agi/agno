"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.langdb import LangDB
from agno.tools.duckduckgo import DuckDuckGo

agent = Agent(
    model=LangDB(id="claude-3-5-sonnet-20240620", project_id="langdb-project-id"),
    tools=[DuckDuckGo()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
