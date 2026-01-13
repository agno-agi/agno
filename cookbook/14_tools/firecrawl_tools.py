"""
This is an example of how to use the FirecrawlTools.

Prerequisites:
- Create a Firecrawl account and get an API key
- Set the API key as an environment variable:
    export FIRECRAWL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.tools.firecrawl import FirecrawlTools

agent = Agent(
    tools=[
        FirecrawlTools(
            enable_scrape=False, enable_crawl=True, enable_search=True, poll_interval=2
        )
    ],
    markdown=True,
)

# Should use search
agent.print_response(
    "Search for the web for the latest on 'web scraping technologies'",
    formats=["markdown", "links"],
)

# Should use crawl
agent.print_response("Summarize this https://docs.agno.com/introduction/")
