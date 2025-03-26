from agno.agent import Agent
from agno.tools.crawl4ai import Crawl4aiTools
from agno.tools.webtools import WebTools
agent = Agent(tools=[Crawl4aiTools(max_length=None),WebTools], show_tool_calls=True)
agent.print_response("Tell me about https://tinyurl.com/k2fkfxra.")
