"""
In this example, we upload a PDF file to Anthropic directly and then use it as an input to an agent.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.anthropic import Claude
from agno.utils.media import download_file
from anthropic import Anthropic

img_path = Path(__file__).parent.joinpath("agno-intro.png")

# Download the file using the download_file function
download_file(
    "https://agno-public.s3.us-east-1.amazonaws.com/images/agno-intro.png",
    str(img_path),
)

# Initialize Anthropic client
client = Anthropic()

# Upload the file to Anthropic
uploaded_file = client.beta.files.upload(
    file=Path(img_path),
)

if uploaded_file is not None:
    agent = Agent(
        model=Claude(
            id="claude-opus-4-20250514",
            betas=["files-api-2025-04-14"],
        ),
        markdown=True,
    )

    agent.print_response(
        "What does the attached image say.",
        images=[Image(content=uploaded_file)],
    )
