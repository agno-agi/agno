from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.aws import AwsBedrock
from agno.utils.media import download_file

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

download_file(
    "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
)

agent = Agent(
    model=AwsBedrock(id="amazon.nova-pro-v1:0"),
    markdown=True,
)

pdf_bytes = pdf_path.read_bytes()

agent.print_response(
    "Give the recipe of Gaeng Kiew Wan Goong",
    files=[File(content=pdf_bytes, format="pdf", name="Thai Recipes")],
)
