from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.firecrawl import FirecrawlTools
from agno.tools.wikipedia import WikipediaTools
from prompts import (
    COMPETITOR_INSTRUCTIONS,
    CRAWLER_INSTRUCTIONS,
    SEARCH_INSTRUCTIONS,
    SUPPLIER_PROFILE_INSTRUCTIONS_GENERAL,
    WIKIPEDIA_INSTRUCTIONS,
)
from pydantic import BaseModel


class SupplierProfile(BaseModel):
    supplier_name: str
    supplier_homepage_url: str
    user_email: str


crawl_agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[FirecrawlTools(crawl=True, limit=5)],
    instructions=CRAWLER_INSTRUCTIONS,
)

search_agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=SEARCH_INSTRUCTIONS,
)

wikipedia_agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[WikipediaTools()],
    instructions=WIKIPEDIA_INSTRUCTIONS,
)

competitor_agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=COMPETITOR_INSTRUCTIONS,
)

profile_agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions=SUPPLIER_PROFILE_INSTRUCTIONS_GENERAL,
)
