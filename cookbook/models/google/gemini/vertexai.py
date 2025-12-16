"""
To use Vertex AI, with the Gemini Model class, you need to set the following environment variables:

export GOOGLE_GENAI_USE_VERTEXAI="true"
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="your-location"

Or you can set the following parameters in the `Gemini` class:

gemini = Gemini(
    vertexai=True,
    project_id="your-google-cloud-project-id",
    location="your-google-cloud-location",
)
"""

import asyncio
import os
from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from agno.utils.media import download_file

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

# Download the file using the download_file function
download_file(
    "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
)

agent = Agent(
    model=Gemini(
        id="gemini-2.5-flash",
        project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION"),
        vertexai=True,
    ),
    markdown=True,
)

# Print the response in the terminal
if __name__ == "__main__":
    asyncio.run(
        agent.aprint_response(
            "Summarize the contents of the attached file.",
            files=[File(filepath=pdf_path)],
        )
    )
