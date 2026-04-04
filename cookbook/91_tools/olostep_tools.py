"""
Olostep Tools - Examples

pip install agno olostep openai
export OLOSTEP_API_KEY=***
export OPENAI_API_KEY=***
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.olostep import OlostepTools

# Example 1: Scrape a single URL
scrape_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[OlostepTools(scrape_url=True)],
    markdown=True,
)
scrape_agent.print_response(
    "Summarize the key features described at https://docs.olostep.com/get-started/welcome"
)

# Example 2: Web search + AI-powered answers
research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OlostepTools(search_web=True, answer_question=True)],
    markdown=True,
)
research_agent.print_response(
    "What are the top web scraping APIs in 2025 and how do they compare on pricing?"
)

# Example 3: Map a site then batch scrape all discovered pages
batch_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OlostepTools(map_website=True, batch_scrape=True)],
    markdown=True,
)
batch_agent.print_response(
    "Map https://docs.olostep.com, find all feature pages, "
    "then batch scrape them and give me a summary of every feature."
)
