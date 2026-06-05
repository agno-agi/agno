"""
Document Workflow Agent
=======================

Work with Drive, Sheets, and Slides together for document workflows.

Use cases:
- Search Drive for files by name or content
- Read data from Sheets
- Find and analyze presentations
- Organize files across folders

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/document_workflow.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.sheets import GoogleSheetsTools
from agno.tools.google.slides import GoogleSlidesTools

auth = GoogleAuth()

agent = Agent(
    name="Document Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleDriveTools(auth=auth),
        GoogleSheetsTools(auth=auth),
        GoogleSlidesTools(auth=auth),
    ],
    instructions=[
        "You help manage and analyze documents in Google Drive.",
        "When searching, try multiple search terms if the first doesn't find results.",
        "Summarize spreadsheet data clearly with key metrics.",
        "For presentations, focus on the main themes and structure.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Search my Drive for any spreadsheets from this week and summarize what data they contain",
        stream=True,
    )
