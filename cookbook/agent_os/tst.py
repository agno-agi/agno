import os

from agno.agent import Agent
from agno.media import File
from agno.models.azure import AzureOpenAI

agent = Agent(
    model=AzureOpenAI(
        id=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    ),
    instructions="You are a helpful assistant. Read the attached PDF to answer.",
    markdown=True,
)

pdf_path = "/absolute/path/to/document.pdf"

agent.print_response(
    "Summarize the attached PDF in 5 bullet points.",
    files=[File(filepath=pdf_path, mime_type="application/pdf")],
    stream=True,
)
