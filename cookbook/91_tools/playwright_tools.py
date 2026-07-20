"""
Playwright Tools
================

Local browser automation via Playwright. No API keys needed.

Requires:
    pip install playwright
    playwright install chromium
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.playwright import PlaywrightTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Enable all browser tools
agent_all = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[PlaywrightTools(headless=True, all=True)],
    instructions=["Always close the browser session when done."],
    markdown=True,
)

# Example 2: Read-only agent (no form interaction)
agent_readonly = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        PlaywrightTools(
            headless=True,
            enable_navigate_to=True,
            enable_screenshot=True,
            enable_get_page_content=True,
            enable_close_session=True,
            enable_click=False,
            enable_type=False,
        )
    ],
    instructions=["Always close the browser session when done."],
    markdown=True,
)

# Example 3: Form automation agent
agent_forms = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        PlaywrightTools(
            headless=True,
            enable_navigate_to=True,
            enable_click=True,
            enable_type=True,
            enable_fill_form=True,
            enable_screenshot=True,
            enable_close_session=True,
        )
    ],
    instructions=["Always close the browser session when done."],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Simple: Extract information from a website
    agent_all.print_response(
        "Go to https://news.ycombinator.com and tell me the top 3 stories",
        stream=True,
    )

    # Multi-page navigation with data extraction
    # agent_all.print_response(
    #     """
    #     1. Go to https://quotes.toscrape.com
    #     2. Extract the first 3 quotes with their authors
    #     3. Click on the first author's name to see their bio
    #     4. Extract the author's birth date and location
    #     5. Go back to the main page
    #     6. Verify you're back on the quotes page
    #     7. Close the session
    #     """,
    #     stream=True,
    # )

    # Pagination: collect data across multiple pages
    # agent_all.print_response(
    #     """
    #     1. Go to https://quotes.toscrape.com
    #     2. Extract all quotes from page 1
    #     3. Click the 'Next' button to go to page 2
    #     4. Extract all quotes from page 2
    #     5. Report the total number of quotes collected
    #     6. Close the session
    #     """,
    #     stream=True,
    # )

    # Form filling
    # agent_forms.print_response(
    #     """
    #     1. Go to https://httpbin.org/forms/post
    #     2. Fill out the form with:
    #        - Customer name: John Doe
    #        - Telephone: 555-123-4567
    #        - Email: john.doe@example.com
    #     3. Take a screenshot at /tmp/form_filled.png
    #     4. Close the session
    #     """,
    #     stream=True,
    # )

    # Take a screenshot
    # agent_readonly.print_response(
    #     "Go to https://example.com and take a screenshot at /tmp/example.png",
    #     stream=True,
    # )
