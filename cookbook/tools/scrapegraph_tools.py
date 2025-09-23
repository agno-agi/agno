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

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.scrapegraph import ScrapeGraphTools

# # Example 1: Default behavior - only smartscraper enabled
# scrapegraph = ScrapeGraphTools(smartscraper=True)

# agent = Agent(tools=[scrapegraph], model=OpenAIChat(id="gpt-4o"), markdown=True, stream=True)

# # Use smartscraper
# agent.print_response("""
# Use smartscraper to extract the following from https://www.wired.com/category/science/:
# - News articles
# - Headlines
# - Images
# - Links
# - Author
# """)

# # Example 2: Only markdownify enabled (by setting smartscraper=False)
# scrapegraph_md = ScrapeGraphTools(smartscraper=False)

# md_agent = Agent(tools=[scrapegraph_md], model=OpenAIChat(id="gpt-4o"), markdown=True)

# # Use markdownify
# md_agent.print_response(
#     "Fetch and convert https://www.wired.com/category/science/ to markdown format"
# )

# # Example 3: Enable searchscraper
# scrapegraph_search = ScrapeGraphTools(searchscraper=True)

# search_agent = Agent(tools=[scrapegraph_search], model=OpenAIChat(id="gpt-4o"), markdown=True)

# # Use searchscraper
# search_agent.print_response(
#     "Use searchscraper to find the CEO of company X and their contact details from https://www.microsoft.com/"
# )

# # Example 4: Enable crawl
# scrapegraph_crawl = ScrapeGraphTools(crawl=True)

# crawl_agent = Agent(tools=[scrapegraph_crawl], model=OpenAIChat(id="gpt-4o"), markdown=True)

# crawl_agent.print_response(
#     "Use crawl to extract what the company does and get text content from privacy and terms from https://scrapegraphai.com/ with a suitable schema."
# )

# Example 5: Enable scrape method for raw HTML content
scrapegraph_scrape = ScrapeGraphTools(scrape=True, smartscraper=False)

scrape_agent = Agent(
    tools=[scrapegraph_scrape],
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
    debug_mode=True,
)

# Use scrape to get raw HTML content
scrape_agent.print_response(
    "Use the scrape tool to get the complete raw HTML content from https://en.wikipedia.org/wiki/2025_FIFA_Club_World_Cup"
)
=======
# Example 1: Enable all ScrapeGraph functions
agent_all = Agent(
    tools=[
        ScrapeGraphTools(
            all=True,  # Enable all ScrapeGraph functions
        )
    ],
    markdown=True,
    stream=True,
)

# Example 2: Enable specific ScrapeGraph functions only
agent_specific = Agent(
    tools=[
        ScrapeGraphTools(
            enable_smartscraper=True,
            enable_markdownify=True,
            enable_searchscraper=False,
            enable_crawl=False,
        )
    ],
    markdown=True,
    stream=True,
)


# Example usage with all functions enabled
print("=== Example 1: Using all ScrapeGraph functions ===")
agent_all.print_response("""
Use any appropriate scraping method to extract comprehensive information from https://www.wired.com/category/science/:
- News articles and headlines
- Convert to markdown if needed
- Search for specific information
""")

# Example usage with specific functions only
print(
    "\n=== Example 2: Using specific ScrapeGraph functions (smartscraper + markdownify) ==="
)
agent_specific.print_response("""
Use smartscraper to extract the following from https://www.wired.com/category/science/:
- News articles
- Headlines  
- Images
- Links
- Author
""")


# Additional examples with specific tool configurations (legacy support)
scrapegraph_md = ScrapeGraphTools(enable_markdownify=True, enable_smartscraper=False)
agent_md = Agent(tools=[scrapegraph_md], markdown=True)

scrapegraph_search = ScrapeGraphTools(enable_searchscraper=True)
agent_search = Agent(tools=[scrapegraph_search], markdown=True)

scrapegraph_crawl = ScrapeGraphTools(enable_crawl=True)
agent_crawl = Agent(tools=[scrapegraph_crawl], markdown=True)

# Commented out to avoid actual API calls
# agent_md.print_response(
#     "Fetch and convert https://www.wired.com/category/science/ to markdown format"
# )

# agent_search.print_response(
#     "Use searchscraper to find the CEO of company X and their contact details from https://example.com"
# )

# agent_crawl.print_response(
#     "Use crawl to extract what the company does and get text content from privacy and terms from https://scrapegraphai.com/ with a suitable schema."
# )
