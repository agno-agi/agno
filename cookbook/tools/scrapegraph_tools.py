from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools

# Example 1: Default behavior - only smartscraper enabled
scrapegraph = ScrapeGraphTools(smartscraper=True)

agent = Agent(tools=[scrapegraph], show_tool_calls=True, markdown=True, stream=True)

# Use smartscraper
agent.print_response("""
Use smartscraper to extract the following from https://www.wired.com/category/science/:
- News articles
- Headlines
- Images
- Links
- Author
""")

# Example 2: Only markdownify enabled (by setting smartscraper=False)
scrapegraph_md = ScrapeGraphTools(smartscraper=False)

agent_md = Agent(tools=[scrapegraph_md], show_tool_calls=True, markdown=True)

# Use markdownify
agent_md.print_response(
    "Fetch and convert https://www.wired.com/category/science/ to markdown format"
)
