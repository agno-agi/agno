"""
This is an example of how to use the StringWebAccessTools.

String Web Access searches the web, fetches any URL as clean Markdown and extracts structured
data from a page, with proxy rotation, anti-bot handling, CAPTCHA solving and JavaScript
rendering handled server-side.

Prerequisites:
- Create a String account and get an API key at https://usestring.ai
- Set the API key as an environment variable:
    export STRING_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.tools.string_web_access import StringWebAccessTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[
        StringWebAccessTools(
            enable_search=True,
            enable_fetch=True,
            main_content_only=True,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Should use search
    agent.print_response(
        "Search the web for the latest on 'anti-bot detection techniques'"
    )

    # Should use fetch, on a page that ordinary requests get blocked from
    agent.print_response(
        "Read https://docs.agno.com/introduction and summarize it in five bullets"
    )

    # Structured extraction is off by default; turn it on when you want typed output back
    extractor = Agent(
        tools=[
            StringWebAccessTools(
                enable_search=False, enable_fetch=False, enable_extract=True
            )
        ],
        markdown=True,
    )
    extractor.print_response(
        "Extract the product name and price from https://books.toscrape.com/catalogue/"
        "a-light-in-the-attic_1000/index.html"
    )
