"""
ScrapeUnblocker Tools - scrape pages that block ordinary HTTP requests.

ScrapeUnblocker renders pages in a real browser behind anti-bot protections
(Cloudflare, DataDome, PerimeterX, Akamai) and returns HTML, AI-parsed JSON,
or Google search results.

Prerequisites:
    pip install agno httpx openai
    export SCRAPEUNBLOCKER_API_KEY=<your-api-key>
    export OPENAI_API_KEY=<your-api-key>

Get an API key at https://www.scrapeunblocker.com
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.scrapeunblocker import ScrapeUnblockerTools

# ---- Create Agent ----

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ScrapeUnblockerTools()],
    markdown=True,
)

# Only scraping, no search:
# agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     tools=[ScrapeUnblockerTools(enable_search_google=False)],
#     markdown=True,
# )

# Parsed JSON instead of raw HTML, through a German exit IP:
# agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     tools=[ScrapeUnblockerTools(parsed_data=True, proxy_country="de")],
#     markdown=True,
# )

# ---- Run Agent ----

if __name__ == "__main__":
    agent.print_response(
        "Scrape https://news.ycombinator.com and summarise the top 5 stories.",
        stream=True,
    )

    # agent.print_response(
    #     "Search Google for 'best web scraping api' and list the top organic results.",
    #     stream=True,
    # )
