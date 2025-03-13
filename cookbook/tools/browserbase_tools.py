from os import getenv

from agno.agent import Agent
from agno.tools.browserbase import BrowserbaseTools

# Browserbase Configuration
# -------------------------------
# These environment variables are required for the BrowserbaseTools to function properly.
# You can set them in your .env file or export them directly in your terminal.

# BROWSERBASE_API_KEY: Your API key from Browserbase dashboard
#   - Required for authentication
#   - Format: Starts with "bb_live_" or "bb_test_" followed by a unique string

# BROWSERBASE_PROJECT_ID: The project ID from your Browserbase dashboard
#   - Required to identify which project to use for browser sessions
#   - Format: UUID string (8-4-4-4-12 format)

# BROWSERBASE_BASE_URL: The Browserbase API endpoint
#   - Optional: Defaults to https://api.browserbase.com if not specified
#   - Only change this if you're using a custom API endpoint or proxy

agent = Agent(
    name="Web Automation Assistant",
    tools=[BrowserbaseTools()],
    instructions=[
        "You are a web automation assistant that can help with:",
        "1. Capturing screenshots of websites",
        "2. Extracting content from web pages",
        "3. Monitoring website changes",
        "4. Taking visual snapshots of responsive layouts",
        "5. Automated web testing and verification",
    ],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

# Content Extraction and SS
# agent.print_response("""
#     Go to https://news.ycombinator.com and extract:
#     1. The page title
#     2. Take a screenshot of the top stories section
# """)

agent.print_response("""
    Visit https://quotes.toscrape.com and:
    1. Extract the first 5 quotes and their authors
    2. Navigate to page 2
    3. Extract the first 5 quotes from page 2
""")
