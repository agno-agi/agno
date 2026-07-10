"""
This is an example of how to use the ScrapeGraphTools.

Prerequisites:
- Create a ScrapeGraphAI account and get an API key at https://scrapegraphai.com
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
    tools=[
        ScrapeGraphTools(
            enable_smartscraper=True, enable_markdownify=True, enable_scrape=True
        )
    ],
    model=OpenAIResponses(id="gpt-5.4"),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Should use smartscraper
    agent.print_response(
        "Use smartscraper on https://example.com to extract the page title and main heading. Return them as JSON.",
        stream=True,
    )

    # Should use markdownify
    agent.print_response(
        "Fetch https://example.com and convert it to markdown. Paste the markdown in your reply.",
        stream=True,
    )

    # Should use scrape
    agent.print_response(
        "Use the scrape tool on https://example.com and confirm whether the HTML contains 'Example Domain'.",
        stream=True,
    )
