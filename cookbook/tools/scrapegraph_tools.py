from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools

"""
ScrapeGraphTools Examples

This script demonstrates the various capabilities of ScrapeGraphTools:

1. smartscraper: Extract structured data using natural language prompts
2. markdownify: Convert web pages to markdown format
3. searchscraper: Search the web and extract information
4. crawl: Crawl websites with structured data extraction
5. scrape: Get raw HTML content from websites (NEW!)

The scrape method is particularly useful when you need:
- Complete HTML source code
- Raw content for further processing
- HTML structure analysis
- Content that needs to be parsed differently

All methods support heavy JavaScript rendering when needed.
"""

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

# Example 5: Enable scrape method for raw HTML content
scrapegraph_scrape = ScrapeGraphTools(scrape=True, smartscraper=False)

agent_scrape = Agent(tools=[scrapegraph_scrape], show_tool_calls=True, markdown=True)

# Use scrape to get raw HTML content
agent_scrape.print_response(
    "Use the scrape tool to get the complete raw HTML content from https://example.com"
)
