"""
Google Drive Toolkit — cookbook examples for all 6 tools.

Setup:
1. Go to Google Cloud Console > APIs & Services > Enable Google Drive API
2. Create OAuth 2.0 credentials (Desktop app)
3. Set env vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID
4. First run opens a browser for consent; token is cached in token.json

Tools:
1. search_files — Search Drive with query syntax
2. list_files — List recent files (delegates to search_files)
3. get_file_metadata — Get file metadata by ID
4. read_file — Read Docs/Sheets/Slides as text, regular files via download
5. upload_file — Upload a local file (disabled by default)
6. download_file — Download a file locally (disabled by default)
"""

from agno.agent import Agent
from agno.tools.google.drive import GoogleDriveTools

agent = Agent(
    tools=[GoogleDriveTools()],
    instructions=[
        "You help users interact with Google Drive.",
        "When listing or searching files, show the file ID, name, and type.",
        "When reading files, summarize the content briefly.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Test 1: List recent files
    agent.print_response("List the 5 most recent files in my Google Drive")

    # Test 2: Search files
    agent.print_response("Search my Google Drive for spreadsheets")

    # Test 3: Read a Google Doc (uncomment and replace with a real file ID)
    # agent.print_response("Read the Google Drive file with ID <FILE_ID> and summarize it")

    # Test 4: Get file metadata (uncomment and replace with a real file ID)
    # agent.print_response("Get metadata for Google Drive file ID <FILE_ID>")
