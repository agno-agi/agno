"""
Drive Document Reader
=====================
Reads and summarizes large documents from Google Drive.

Uses max_read_size to control the maximum file size loaded into memory
and returns structured summaries with key sections.

Key concepts:
- read_file: Exports Google Docs as text, Sheets as CSV, Slides as text
- add_datetime_to_context: Agent knows today's date for time-relative queries

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools

# 50 MB — allow reading larger non-Workspace files (default is 10 MB)
MAX_READ_SIZE = 50 * 1024 * 1024

agent = Agent(
    name="Document Reader",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools(max_read_size=MAX_READ_SIZE)],
    instructions=[
        "When reading documents, provide a structured summary with sections and key points.",
        "For spreadsheets (returned as CSV), describe the columns and highlight notable data.",
        "If the content is truncated, tell the user and summarize what was available.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Search and read a document
    agent.print_response(
        "Find the most recent Google Doc in my Drive and summarize it",
        stream=True,
    )

    # Read a specific file by ID
    # agent.print_response(
    #     "Read the file with ID <FILE_ID> and give me a detailed summary",
    #     stream=True,
    # )

    # Read a spreadsheet
    # agent.print_response(
    #     "Find a spreadsheet named 'Budget' and describe what data it contains",
    #     stream=True,
    # )
