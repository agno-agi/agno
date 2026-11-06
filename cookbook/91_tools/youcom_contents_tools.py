"""
You.com Contents Tools
=============================

Demonstrates the YouContentsTools toolkit which exposes the You.com Contents API
as a first-class Agno tool. The Contents API returns the raw content (HTML, Markdown)
and metadata of target webpages.

Set ``YDC_API_KEY`` in your environment before running this example.
Get a key at https://you.com/platform/api-keys.
"""

import os

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools.youcom.contents import YouContentsTools
from dotenv import load_dotenv

load_dotenv()

agent = Agent(
    id="You_Contents_Agent",
    model=OpenAILike(
        id="gpt-5.4-mini",
        api_key=os.getenv("Azure_API_KEY"),
        base_url=os.getenv("Azure_Endpoint"),
        request_params={"parallel_tool_calls": False},
    ),
    tools=[
        YouContentsTools(
            format="markdown",  # readable output, not raw JSON
            show_results=True,  # logs full response before agent sees it
            crawl_timeout=15,  # max time to wait for the page content
        ),
    ],
    tool_call_limit=3,
    debug_mode=True,
    debug_level=2,  # shows tool call params + raw response
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Fetch the markdown content of https://en.wikipedia.org/wiki/Main_Page and summarize the main topics.",
        markdown=True,
    )
