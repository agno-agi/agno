from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.brightdata import BrightDataTools
from agno.utils.media import save_base64_data

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        BrightDataTools(
            get_screenshot=True,
        )
    ],
    markdown=True,
    show_tool_calls=True,
)

# Example 1: Scrape a webpage as Markdown
agent.print_response(
    "Scrape this webpage as markdown: https://docs.agno.com/introduction",
)

# Example 2: Take a screenshot of a webpage
# agent.print_response(
#     "Take a screenshot of this webpage: https://docs.agno.com/introduction",
# )

# response = agent.run_response
# if response.images:
#     save_base64_data(response.images[0].content, "tmp/agno_screenshot.png")

# Add a new SERP API zone: https://brightdata.com/cp/zones/new
# Example 3: Search using Google
# agent.print_response(
#     "Search Google for 'Python web scraping best practices' and give me the top 5 results",
# )

# Example 4: Get structured data from Amazon product
# agent.print_response(
#     "Get detailed product information from this Amazon product: https://www.amazon.com/dp/B0D2Q9397Y?th=1&psc=1",
# )

# Example 5: Get LinkedIn profile data
# agent.print_response(
#     "Search for Satya Nadella on LinkedIn and give me a summary of his profile"
# )
