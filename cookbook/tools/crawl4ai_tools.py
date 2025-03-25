from agno.agent import Agent
from agno.tools.crawl4ai import Crawl4aiTools

agent = Agent(tools=[Crawl4aiTools(max_length=None,expand_url=True)], show_tool_calls=True)
agent.print_response("Tell me about https://tinyurl.com/k2fkfxra.")
