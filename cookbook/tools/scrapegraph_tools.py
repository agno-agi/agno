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

# Example 3: Enable searchscraper
scrapegraph_search = ScrapeGraphTools(searchscraper=True)

agent_search = Agent(tools=[scrapegraph_search], show_tool_calls=True, markdown=True)

# Use searchscraper
agent_search.print_response(
    "Use searchscraper to find the CEO of company X and their contact details from https://example.com"
)

# Example 4: Enable crawl
scrapegraph_crawl = ScrapeGraphTools(crawl=True)

agent_crawl = Agent(tools=[scrapegraph_crawl], show_tool_calls=True, markdown=True)

# Use crawl (schema must be provided as a dict in the tool call)
agent_crawl.print_response(
    "Use crawl to extract what the company does and get text content from privacy and terms from https://scrapegraphai.com/ with a suitable schema."
)
