"""Run `pip install duckduckgo-search` to install dependencies."""

from phi.agent import Agent
from phi.model.langdb import LangDB
from phi.tools.duckduckgo import DuckDuckGo

agent = Agent(model=LangDB(id="gpt-4o"), tools=[DuckDuckGo()], show_tool_calls=True, markdown=True)
agent.print_response("Whats happening in France?", stream=True)
