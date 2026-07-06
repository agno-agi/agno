"""
This is an example of how to use the CrwTools.

fastCRW is a Firecrawl-compatible web scraper (single binary; self-host or cloud).

Prerequisites:
- Create a fastCRW account and get an API key
- Set the API key as an environment variable:
    export CRW_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.tools.crw import CrwTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    tools=[
        CrwTools(
            enable_scrape=False, enable_crawl=True, enable_search=True, poll_interval=2
        )
    ],
    markdown=True,
)

# Should use search

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Search for the web for the latest on 'web scraping technologies'",
        formats=["markdown", "links"],
    )

    # Should use crawl
    agent.print_response("Summarize this https://docs.agno.com/introduction/")
