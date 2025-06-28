from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.serper import SerperTools

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    tools=[SerperTools()],
    show_tool_calls=True,
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

# Example 3: Reviews Search
# agent.print_response(
#     "Use this Google Place ID: ChIJ_Yjh6Za1j4AR8IgGUZGDDTs and analyze the reviews",
#     markdown=True
# )

# Example 4: Web Scraping
# agent.print_response(
#     "Scrape and summarize the main content from this OpenAI blog post: https://openai.com/index/gpt-4/",
#     markdown=True
# )
