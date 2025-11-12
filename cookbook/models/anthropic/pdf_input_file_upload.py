"""
In this example, we upload a PDF file to Anthropic directly and then use it as an input to an agent.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude
from agno.utils.media import download_file
from anthropic import Anthropic

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

# Download the file using the download_file function
download_file(
    "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
)

# Initialize Anthropic client
client = Anthropic()

# Upload the file to Anthropic
uploaded_file = client.beta.files.upload(
    file=Path(pdf_path),
)

if uploaded_file is not None:
    agent = Agent(
        model=Claude(id="claude-opus-4-20250514", betas=["files-api-2025-04-14"]),
        markdown=True,
    )

    agent.print_response(
        "Summarize the contents of the attached file.",
        files=[File(external=uploaded_file)],
    )
