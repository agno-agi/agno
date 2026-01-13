from agno.agent import Agent
from agno.tools.playwright import PlaywrightTools

# Create an agent with PlaywrightTools
# headless=True runs the browser without a visible window (faster, good for automation)
# headless=False shows the browser window (useful for debugging)
agent = Agent(
    name="Local Web Automation Agent",
    tools=[PlaywrightTools(headless=True, timeout=60000)],
    instructions=[
        "You are a web automation assistant using a local browser.",
        "You can navigate to websites, interact with elements, and extract data.",
        "Available actions:",
        "- Navigate to URLs and take screenshots",
        "- Click buttons and fill forms",
        "- Extract text content from pages",
        "- Submit forms and wait for dynamic content",
    ],
    markdown=True,
)

# Example 1: Basic Navigation and Content Extraction
# agent.print_response("""
#     Navigate to https://quotes.toscrape.com and:
#     1. Get the page title
#     2. Extract the first 3 quotes with their authors
# """)

# Example 2: Form Interaction
# agent.print_response("""
#     Go to https://quotes.toscrape.com/login and:
#     1. Fill in the username field with "test_user"
#     2. Fill in the password field with "test_pass"
#     3. Take a screenshot of the filled form
# """)

# Example 3: Navigation and Screenshots
# agent.print_response("""
#     Visit https://news.ycombinator.com and:
#     1. Take a screenshot of the homepage
#     2. Extract the titles of the top 5 stories
#     3. Click on the first story link
#     4. Take a screenshot of the article page
# """)

# Example 4: Dynamic Content Extraction
agent.print_response("""
    Go to https://quotes.toscrape.com and:
    1. Extract all quotes from page 1
    2. Navigate to page 2 by clicking the "Next" button
    3. Extract all quotes from page 2
    4. Compare the number of quotes on each page
""")
