from agno.agent import Agent
from agno.db.base import BaseDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.models.anthropic import Claude
from agno.tools.firecrawl import FirecrawlTools
from textwrap import dedent

def get_memory_agent(db: BaseDb) -> Agent:

    return Agent(
        name="Memory Agent",
        id="memory-agent",
        model=OpenAIChat(id="gpt-4.1"),
        add_history_to_context=True,
        num_history_runs=5,
        add_datetime_to_context=True,
        markdown=True,
        # Set a database
        db=db,
        # Enable memory
        enable_user_memories=True,
        # Add a tool to search the web
        tools=[DuckDuckGoTools()],
    )


def get_web_search_agent(db: BaseDb) -> Agent:
    # ************* Description *************
    description = dedent(
        """\
        You are a Web Search Agent, an advanced AI Agent specialized in searching the web for information.
        Your goal is to help users find the information they need on the web.
    """
    )

    instructions = dedent(
        """\
        Call the Firecrawl tool to search the web for information.
        - Use `search` to search the web for information.
        - Use `scrape_website` to scrape a specified website.

    """
    )

    return Agent(
        name="Web Search Agent",
        id="web-search-agent",
        model=Claude(id="claude-sonnet-4-0"),
        description=description,
        db=db,
        enable_user_memories=True,
        add_history_to_context=True,
        add_datetime_to_context=True,
        markdown=True,
        tools=[FirecrawlTools(enable_scrape=True, enable_search=True)],
    )
