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

# Create agent with default AgentQL tool
agent = Agent(
    model=OpenAIChat(id="gpt-4o"), tools=[AgentQLTools()], show_tool_calls=True
)
agent.print_response("https://docs.agno.com/introduction", markdown=True)

# Define custom AgentQL query for specific data extraction (see https://docs.agentql.com/concepts/query-language)
custom_query = """
{
    title
    text_content[]
}
"""

# Create AgentQL tool with custom query
custom_scraper = AgentQLTools(agentql_query=custom_query)

# Create agent with custom AgentQL tool
custom_agent = Agent(
    model=OpenAIChat(id="gpt-4o"), tools=[custom_scraper], show_tool_calls=True
)
custom_agent.print_response("https://docs.agno.com/introduction", markdown=True)
