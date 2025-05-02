from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.openai import OpenAIChat
from agno.utils.media import download_file

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

# Download the file using the download_file function
download_file(
    "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
    add_history_to_messages=True,
)

agent.print_response(
    "What is the recipe for Gaeng Som Phak Ruam? Also what are the health benefits. Refer to the attached file.",
    files=[File(filepath=pdf_path)],
)
