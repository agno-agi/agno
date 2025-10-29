"""
This is a example of an agent using the Serper Toolkit.

You can obtain an API key from https://serper.dev/

 - Set your API key as an environment variable: export SERPER_API_KEY="your_api_key_here"
 - or pass api_key to the SerperTools class
"""

from agno.agent import Agent
from agno.tools.serper import SerperTools

agent = Agent(
    tools=[SerperTools()],
)

agent.print_response(
    "Search for the latest news about artificial intelligence developments",
    markdown=True,
)

# Example 2: Google Scholar Search
# agent.print_response(
#     "Find 2 recent academic papers about large language model safety and alignment",
#     markdown=True,
# )

# Example 3: Web Scraping
# agent.print_response(
#     "Scrape and summarize the main content from this OpenAI blog post: https://openai.com/index/gpt-4/",
#     markdown=True
# )
