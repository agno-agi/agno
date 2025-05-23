"""
In this example, we upload a PDF file to Anthropic directly and then use it as an input to an agent.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude
from anthropic import Anthropic

# Initialize Anthropic client
client = Anthropic()

# Upload the file to Anthropic
file_path = Path(
    "libs/agno/tests/integration/knowledge/data/thai_recipes_short.pdf")
uploaded_file = client.beta.files.upload(
    file=file_path,
)

print('Uploaded file:', uploaded_file)

if uploaded_file is not None:
    agent = Agent(
        model=Claude(
            id="claude-opus-4-20250514",
            default_headers={
                "anthropic-beta": "code-execution-2025-05-22"
            },
        ),
        markdown=True,
    )

    agent.print_response(
        "Summarize the contents of the attached file.",
        files=[File(external=uploaded_file)],
    )
