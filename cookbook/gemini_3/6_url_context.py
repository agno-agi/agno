"""
URL Context - Read and Compare Web Pages
==========================================
Fetch and read web pages natively. Just set url_context=True on the model.

Key concepts:
- url_context=True: Enables Gemini to fetch and read URLs from the prompt
- Native capability: The model handles HTTP requests internally
- No extra tools: Unlike web scraping, this needs no additional packages
- Best with Pro: URL context works better with Gemini Pro models

Example prompts to try:
- "Compare the recipes at these two URLs"
- "Summarize the key points from this article: <URL>"
- "What are the differences between these two product pages?"
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a comparison expert. Analyze content from URLs and provide
clear, structured comparisons.

## Rules

- Read all provided URLs thoroughly
- Use tables for side-by-side comparisons
- Highlight key differences and similarities
- Be specific, cite details from each source
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
url_agent = Agent(
    name="URL Context Agent",
    # url_context=True lets Gemini fetch and read URLs from the prompt
    model=Gemini(id="gemini-3.1-pro-preview", url_context=True),
    instructions=instructions,
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
URL context use cases:

1. Compare two articles
   "Compare the arguments in <url1> vs <url2>"

2. Summarize a long page
   "Summarize the key takeaways from <url>"

3. Extract structured data from a page
   agent = Agent(model=Gemini(id="...", url_context=True), output_schema=MySchema)
   result = agent.run("Extract product details from <url>")

4. Research across multiple sources
   "What do these 3 articles say about <topic>? <url1> <url2> <url3>"

Note: URL context reads the page content at request time. The model
does not cache pages between requests.
"""
