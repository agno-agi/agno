from agno.agent import Agent
from agno.tools.firecrawl import FirecrawlTools

agent = Agent(
    tools=[FirecrawlTools(scrape=False, crawl=True, search=True)],
    show_tool_calls=True,
    markdown=True,
)

# Should use search
agent.print_response("Search for the web for the latest on 'web scraping technologies'", formats=["markdown", "links"])

# Should use crawl
agent.print_response("Summarize this https://finance.yahoo.com/")
