from os import getenv

from agno.agent import Agent
from agno.tools.browserbase import BrowserbaseTools

agent = Agent(
    name="Web Automation Assistant",
    tools=[
        BrowserbaseTools(
            api_key=getenv("BROWSERBASE_API_KEY"),
            project_id=getenv("BROWSERBASE_PROJECT_ID"),
        )
    ],
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
agent.print_response("""
    Go to https://news.ycombinator.com and extract:
    1. The page title
    3. Take a screenshot of the top stories section
""")

# agent.print_response("""
#     Visit https://quotes.toscrape.com and:
#     1. Extract the first 5 quotes and their authors
#     2. Navigate to page 2
#     3. Extract the first 5 quotes from page 2
# """)
