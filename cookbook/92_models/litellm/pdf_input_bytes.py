from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.litellm import LiteLLM
from agno.utils.media import download_file

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

download_file(
    "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
)

agent = Agent(
    model=LiteLLM(id="openai/gpt-4o"),
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file.",
    files=[
        File(
            content=pdf_path.read_bytes(),
        ),
    ],
)
