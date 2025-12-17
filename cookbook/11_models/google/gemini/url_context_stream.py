"""Run `pip install google-generativeai` to install dependencies."""

from agno.agent import Agent
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.5-flash", url_context=True),
    markdown=True,
)

url1 = "https://www.foodnetwork.com/recipes/ina-garten/perfect-roast-chicken-recipe-1940592"
url2 = "https://www.allrecipes.com/recipe/83557/juicy-roasted-chicken/"

response = agent.run(
    f"Compare the ingredients and cooking times from the recipes at {url1} and {url2}",
    stream=True,
)

for chunk in response:
    if chunk.citations is not None:
        print("Citations:")
        if chunk.citations.urls:
            print(chunk.citations.urls)
    if chunk.content:
        print(chunk.content, end="", flush=True)
