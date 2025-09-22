from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools

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
