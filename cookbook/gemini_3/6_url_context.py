"""
6. URL Context
==============
Gemini can fetch and read web pages natively with url_context=True.
No scraping tools needed -- just pass URLs in your prompt.

Run:
    python cookbook/gemini_3/6_url_context.py

Example prompt:
    "Compare the recipes at these two URLs"
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
url_agent = Agent(
    name="URL Context Agent",
    model=Gemini(id="gemini-3.1-pro-preview", url_context=True),
    instructions="You are a comparison expert. Analyze content from URLs and provide clear, structured comparisons.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url1 = "https://www.foodnetwork.com/recipes/ina-garten/perfect-roast-chicken-recipe-1940592"
    url2 = "https://www.allrecipes.com/recipe/83557/juicy-roasted-chicken/"

    url_agent.print_response(
        f"Compare the ingredients and cooking times from the recipes at {url1} and {url2}",
        stream=True,
    )
