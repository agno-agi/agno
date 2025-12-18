"""Google Search with Gemini.

The search tool enables Gemini to access current information from Google Search.
This is useful for getting up-to-date facts, news, and web content.

Run `pip install google-generativeai` to install dependencies.
"""

from agno.agent import Agent
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.5-flash", search=True),
    markdown=True,
)

# Ask questions that require current information
response = agent.run(
    "What are the latest developments in AI technology this week?", stream=True
)
response_str = ""
print("Citations:")
print("=" * 80)
for chunk in response:
    if chunk.content:
        response_str += chunk.content
    if chunk.citations is not None:
        if chunk.citations.urls:
            for url in chunk.citations.urls:
                print(f"URL: {url.url}, Title: {url.title}")
        if chunk.citations.search_queries:
            for query in chunk.citations.search_queries:
                print(f"Search Query: {query}")

print("=" * 80)
print("Response:")
print("=" * 80)
print(response_str)
