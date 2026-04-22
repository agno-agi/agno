"""ScrapeGraphTools — web scraping, extraction, search, and crawl via the ScrapeGraphAI API.

Setup:
    pip install -U agno scrapegraph-py openai
    export SGAI_API_KEY=<your key>  # https://scrapegraphai.com
    export OPENAI_API_KEY=<your key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.scrapegraph import ScrapeGraphTools

agent_model = OpenAIResponses(id="gpt-5.4")
scrapegraph_smartscraper = ScrapeGraphTools(enable_smartscraper=True)

agent = Agent(
    tools=[scrapegraph_smartscraper],
    model=agent_model,
    markdown=True,
    stream=True,
)

if __name__ == "__main__":
    agent.print_response(
        """
        Use smartscraper to extract the following from https://www.wired.com/category/science/:
        - News articles
        - Headlines
        - Images
        - Links
        - Author
        """
    )

    # Example 2: Only markdownify enabled (by setting smartscraper=False)
    # scrapegraph_md = ScrapeGraphTools(enable_smartscraper=False)
    # md_agent = Agent(tools=[scrapegraph_md], model=agent_model, markdown=True)
    # md_agent.print_response(
    #     "Fetch and convert https://www.wired.com/category/science/ to markdown format"
    # )

    # Example 3: Enable crawl (polls until the crawl job completes upstream)
    # scrapegraph_crawl = ScrapeGraphTools(enable_crawl=True)
    # crawl_agent = Agent(tools=[scrapegraph_crawl], model=agent_model, markdown=True)
    # crawl_agent.print_response(
    #     "Use crawl to extract what the company does and get text content from privacy "
    #     "and terms from https://scrapegraphai.com/ with a suitable schema."
    # )

    # Example 4: Enable scrape method for raw HTML content
    # scrapegraph_scrape = ScrapeGraphTools(enable_scrape=True, enable_smartscraper=False)
    # scrape_agent = Agent(
    #     tools=[scrapegraph_scrape], model=agent_model, markdown=True, stream=True
    # )
    # scrape_agent.print_response(
    #     "Use the scrape tool to get the complete raw HTML content from "
    #     "https://en.wikipedia.org/wiki/2025_FIFA_Club_World_Cup"
    # )

    # Example 5: Enable all ScrapeGraph functions; render_heavy_js=True uses JS rendering.
    # scrapegraph_all = Agent(
    #     tools=[ScrapeGraphTools(all=True, render_heavy_js=True)],
    #     model=agent_model,
    #     markdown=True,
    #     stream=True,
    # )
    # scrapegraph_all.print_response(
    #     """
    #     Use any appropriate scraping method to extract comprehensive information
    #     from https://www.wired.com/category/science/:
    #     - News articles and headlines
    #     - Convert to markdown if needed
    #     - Search for specific information
    #     """
    # )
