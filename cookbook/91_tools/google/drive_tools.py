"""
Google Drive Tools
==================
Core examples: read-only agent, full-access agent with upload and download.

All five Drive tools are demonstrated: list_files, search_files,
read_file, upload_file, download_file.

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Read-only agent (default -- upload and download disabled)
read_only_agent = Agent(
    name="Drive Reader",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools()],
    instructions=[
        "When listing or searching files, show the file ID, name, type, and last modified date.",
        "When reading files, summarize the content briefly.",
        "Google Docs and Slides are exported as plain text, Sheets as CSV.",
    ],
    markdown=True,
)

# Full-access agent with upload and download enabled
full_agent = Agent(
    name="Drive Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools(upload_file=True, download_file=True)],
    instructions=[
        "When uploading files, confirm the file path with the user first.",
        "When downloading files, ask for the destination path.",
        "Show file metadata in a structured markdown format.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # list_files
    read_only_agent.print_response(
        "List the 5 most recent files in my Google Drive",
        stream=True,
    )

    # search_files
    read_only_agent.print_response(
        "Search my Google Drive for spreadsheets",
        stream=True,
    )

    # read_file
    # read_only_agent.print_response(
    #     "Read the file with ID <FILE_ID> and summarize it",
    #     stream=True,
    # )

    # upload_file (requires full_agent)
    # full_agent.print_response(
    #     "Upload the file at /path/to/document.pdf to my Google Drive",
    #     stream=True,
    # )

    # download_file (requires full_agent)
    # full_agent.print_response(
    #     "Download the file with ID <FILE_ID> to /tmp/report.csv",
    #     stream=True,
    # )
