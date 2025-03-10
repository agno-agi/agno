from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

# Please download the file using
# wget https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf

pdf_path = Path(__file__).parents[4].joinpath("ThaiRecipes.pdf")

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file.",
    files=[File(filepath=pdf_path)],
)
