"""
In this example, we upload a PDF file to Google GenAI directly and then use it as an input to an agent.

Note: If the size of the file is greater than 20MB, and a file path is provided, the file automatically gets uploaded to Google GenAI.
"""

from pathlib import Path
from time import sleep

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from google import genai

pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")

client = genai.Client()

# Upload the file to Google GenAI
upload_result = client.files.upload(file=pdf_path)

# Get the file from Google GenAI
retrieved_file = client.files.get(name=upload_result.name)

# Retry up to 3 times if file is not ready
retries = 0
wait_time = 5
while retrieved_file is None and retries < 3:
    retries += 1
    sleep(wait_time)
    retrieved_file = client.files.get(name=upload_result.name)

if retrieved_file is not None:
    agent = Agent(
        model=Gemini(id="gemini-2.0-flash-exp"),
        markdown=True,
        add_history_to_messages=True,
    )

    agent.print_response(
        "Summarize the contents of the attached file.",
        files=[File(external=retrieved_file)],
    )

    agent.print_response(
        "Suggest me a recipe from the attached file.",
    )
else:
    print("Error: File was not ready after multiple attempts.")
