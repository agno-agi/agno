"""
This is an example of how to use the ScrapeGraphTools.

Prerequisites:
- Create a ScrapeGraphAI account and get an API key
- Set the API key as an environment variable:
    export SGAI_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.scrapegraph import ScrapeGraphTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ScrapeGraphTools(
            enable_smartscraper=True, enable_markdownify=True, enable_scrape=True
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Should use smartscraper
    agent.print_response(
        "Use smartscraper on https://example.com to extract the page title and main heading as JSON."
    )

    # Should use markdownify
    agent.print_response("Convert https://example.com to markdown.")

    # Should use scrape
    agent.print_response(
        "Use scrape on https://example.com and confirm whether the HTML contains 'Example Domain'."
    )
