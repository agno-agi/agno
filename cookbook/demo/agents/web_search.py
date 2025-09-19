from textwrap import dedent

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.tools.firecrawl import FirecrawlTools

# ************* Database Setup *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url, id="agno_assist_db")
# *******************************


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
# *******************************

# ************* Agent *************
web_search_agent = Agent(
    name="Web Search Agent",
    id="web-search-agent",
    model=Claude(id="claude-sonnet-4-0"),
    description=description,
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
    tools=[
        FirecrawlTools(
            enable_scrape=True,
            enable_search=True,
        ),
    ],
)
# *******************************
