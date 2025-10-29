"""
AgentQL Tools for scraping websites.

Prerequisites:
- Set the environment variable `AGENTQL_API_KEY` with your AgentQL API key.
  You can obtain the API key from the AgentQL website:
  https://agentql.com/
- Run `playwright install` to install a browser extension for playwright.

AgentQL will open up a browser instance (don't close it) and do scraping on the site.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.agentql import AgentQLTools

# Example 1: Enable specific AgentQL functions
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        AgentQLTools(
            enable_scrape_website=True,
            enable_custom_scrape_website=False,
            agentql_query="your_query_here",
        )
    ],
)

# Example 2: Enable all AgentQL functions
agent_all = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[AgentQLTools(all=True, agentql_query="your_query_here")],
)

# Example 3: Custom query with specific function enabled
custom_query = """
{
    title
    text_content[]
}
"""

custom_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        AgentQLTools(
            enable_scrape_website=True,
            enable_custom_scrape_website=True,
            agentql_query=custom_query,
        )
    ],
)

# Test the agents
agent.print_response(
    "Scrape the main content from https://docs.agno.com/introduction", markdown=True
)
custom_agent.print_response(
    "Extract title and content from https://docs.agno.com/introduction", markdown=True
)
