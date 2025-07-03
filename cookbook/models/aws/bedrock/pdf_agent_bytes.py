from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.aws import AwsBedrock
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.media import download_file

agent = Agent(
    model=AwsBedrock(id="amazon.nova-pro-v1:0"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

file_path = Path(__file__).parent.joinpath("sample.pdf")

download_file(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    output_path=str(file_path),
)

# Read the PDF file content as bytes
pdf_bytes = file_path.read_bytes()

agent.print_response(
    "Give me the tastiest recipe in this document.",
    files=[
        File(content=pdf_bytes, format="pdf", name="Thai Recipes"),
    ],
)
