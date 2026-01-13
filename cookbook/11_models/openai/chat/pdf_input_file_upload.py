"""
In this example, we upload a PDF file to Google GenAI directly and then use it as an input to an agent.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.openai import OpenAIChat

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

# Pass the local PDF file path directly; the client will inline small files or upload large files automatically
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
    add_history_to_context=True,
)

agent.print_response(
    "Suggest me a recipe from the attached file.",
    files=[File(filepath=str(pdf_path))],
)
