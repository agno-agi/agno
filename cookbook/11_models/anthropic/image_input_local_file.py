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


agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    markdown=True,
)

agent.print_response(
    "What does the attached image say.",
    images=[Image(filepath=img_path)],
)
