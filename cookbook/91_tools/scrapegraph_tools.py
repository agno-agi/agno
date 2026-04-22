"""ScrapeGraphTools — web scraping, extraction, search, and crawl via the ScrapeGraphAI API.

Setup:
    pip install -U agno scrapegraph-py openai
    export SGAI_API_KEY=<your key>  # https://scrapegraphai.com
    export OPENAI_API_KEY=<your key>

Running this file exercises three tools in sequence (smartscraper, markdownify,
scrape). The primary `smartscraper_agent` is also importable from this module.
Further variants (searchscraper, crawl, all=True + render_heavy_js) are listed
at the bottom, commented out, for selective enabling.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.scrapegraph import ScrapeGraphTools

agent_model = OpenAIResponses(id="gpt-5.4")

# Primary agent — structured extraction via an AI prompt.
smartscraper_agent = Agent(
    tools=[ScrapeGraphTools(enable_smartscraper=True)],
    model=agent_model,
    markdown=True,
)

# Additional demo agents (markdownify + scrape) — defined here so they're
# importable too; executed at the bottom when this file is run directly.
markdownify_agent = Agent(
    tools=[ScrapeGraphTools(enable_smartscraper=False, enable_markdownify=True)],
    model=agent_model,
    markdown=True,
)

scrape_agent = Agent(
    tools=[ScrapeGraphTools(enable_scrape=True, enable_smartscraper=False)],
    model=agent_model,
    markdown=True,
)


if __name__ == "__main__":
    # 1. smartscraper — URL + prompt -> structured JSON.
    smartscraper_agent.print_response(
        "Use smartscraper on https://example.com to extract the page title and main heading. "
        "Return them as JSON.",
        stream=True,
    )

    # 2. markdownify — URL -> markdown text.
    markdownify_agent.print_response(
        "Fetch https://example.com and convert it to markdown. Paste the markdown in your reply.",
        stream=True,
    )

    # 3. scrape — URL -> raw HTML.
    scrape_agent.print_response(
        "Use the scrape tool on https://example.com and confirm whether the HTML contains 'Example Domain'.",
        stream=True,
    )

    # 4. searchscraper — web search with extraction across top results.
    # search_agent = Agent(
    #     tools=[ScrapeGraphTools(enable_searchscraper=True, enable_smartscraper=False)],
    #     model=agent_model,
    #     markdown=True,
    # )
    # search_agent.print_response(
    #     "Use searchscraper to find what example.com is used for and summarise the top results.",
    #     stream=True,
    # )

    # 5. crawl — multi-page extraction. Polls until the upstream job completes (up to ~3 minutes).
    # crawl_agent = Agent(
    #     tools=[ScrapeGraphTools(enable_crawl=True)],
    #     model=agent_model,
    #     markdown=True,
    # )
    # crawl_agent.print_response(
    #     "Use crawl on https://scrapegraphai.com/ with depth=1 and max_pages=1. "
    #     'Prompt="what does this company do?" '
    #     'Schema={"type": "object", "properties": {"summary": {"type": "string"}}}.',
    #     stream=True,
    # )

    # 6. all=True with JS rendering — one toolkit exposing every method.
    # all_agent = Agent(
    #     tools=[ScrapeGraphTools(all=True, render_heavy_js=True)],
    #     model=agent_model,
    #     markdown=True,
    # )
    # all_agent.print_response(
    #     "Pick the best ScrapeGraph tool to get the main heading of https://example.com.",
    #     stream=True,
    # )
