"""
Document Workflow Agent
=======================

Work with Drive, Sheets, and Slides together for document workflows.

Use cases:
- Search Drive for files by name or content
- Read data from Sheets
- Find and analyze presentations
- Organize files across folders

Setup:
  1. Enable Drive, Sheets, and Slides APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Set env vars:
     - GOOGLE_CLIENT_ID
     - GOOGLE_CLIENT_SECRET
     - GOOGLE_TOKEN_ENCRYPTION_KEY (generate with: python -c "from agno.utils.encryption import generate_encryption_key; print(generate_encryption_key())")

First run opens browser for OAuth consent, saves encrypted token to DB.
Subsequent runs load the encrypted token — no re-auth needed.

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/workspace/document_workflow.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import AuthConfig
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.sheets import GoogleSheetsTools
from agno.tools.google.slides import GoogleSlidesTools
from agno.utils.encryption import generate_encryption_key  # noqa: F401

# Token encryption: set GOOGLE_TOKEN_ENCRYPTION_KEY env var (recommended)
# Or pass explicitly: AuthConfig(db=db, token_encryption_key=generate_encryption_key())
db = SqliteDb(db_file="tmp/document_workflow.db")
auth = AuthConfig(db=db)

agent = Agent(
    name="Document Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
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
