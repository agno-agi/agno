from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file.",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)
