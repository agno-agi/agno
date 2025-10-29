from agno.agent import Agent
from agno.tools.spider import SpiderTools

# Example 1: All functions available (default behavior)
agent_all = Agent(
    name="Spider Agent - All Functions",
    tools=[SpiderTools(optional_params={"proxy_enabled": True})],
    instructions=["You have access to all Spider web scraping capabilities."],
    markdown=True,
)

# Example 2: Include specific functions only
agent_specific = Agent(
    name="Spider Agent - Search Only",
    tools=[SpiderTools(enable_crawl=False, optional_params={"proxy_enabled": True})],
    instructions=["You can only search the web, no scraping or crawling."],
    markdown=True,
)


# Use the default agent for examples
agent = agent_all

agent.print_response(
    'Can you scrape the first search result from a search on "news in USA"?'
)
