"""
This is an example of how to use CrwTools.

CRW is a high-performance, Firecrawl-compatible web scraper for AI agents.
Single binary, ~6 MB idle RAM, 5.5x faster than Firecrawl.

Prerequisites:
- A running CRW server (self-hosted or fastcrw.com cloud)
    # Option A: Self-hosted
    cargo install crw-server && crw-server

    # Option B: Cloud
    export CRW_API_KEY="fc-..."
"""

from agno.agent import Agent
from agno.tools.crw import CrwTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[
        CrwTools(
            api_url="http://localhost:3000",
            enable_scrape=True,
            enable_crawl=True,
            enable_map=True,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Scrape a single page
    agent.print_response("Summarize the content of https://news.ycombinator.com")

    # Map site structure
    agent.print_response("List all pages on https://docs.agno.com")

    # Crawl multiple pages
    agent.print_response("Crawl https://docs.agno.com/introduction/ and give me a summary")
