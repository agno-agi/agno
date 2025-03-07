from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude

# Please download the file using
# wget https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf

pdf_path = Path(__file__).parents[3].joinpath("ThaiRecipes.pdf")

agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20241022"),
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file.",
    files=[
        File(
            filepath=pdf_path,
        ),
    ],
    stream=True,
)
