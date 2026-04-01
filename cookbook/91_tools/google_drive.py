"""
Google Drive Agent that can search, list, read, upload, and download files using Google Drive.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Read-only Drive agent (default — upload and download disabled)
read_only_agent = Agent(
    name="Drive Reader Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools()],
    description="You are a Google Drive specialist that can search and read files.",
    instructions=[
        "You can search, list, and read files from the user's Google Drive.",
        "When listing or searching files, show the file ID, name, type, and last modified date.",
        "When reading files, summarize the content briefly.",
        "Google Docs and Slides are exported as plain text, Sheets as CSV.",
    ],
    markdown=True,
)

# Example 2: Full Drive agent with upload enabled
full_drive_agent = Agent(
    name="Full Drive Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools(upload_file=True, download_file=True)],
    description="You are a Google Drive agent with full read and write capabilities.",
    instructions=[
        "You can search, list, read, upload, and download files from Google Drive.",
        "When uploading files, confirm the file path with the user first.",
        "When downloading files, ask for the destination path.",
        "Show file metadata in a structured markdown format.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: List recent files
    read_only_agent.print_response(
        "List the 5 most recent files in my Google Drive",
        stream=True,
    )

    # Example 2: Search for specific file types
    read_only_agent.print_response(
        "Search my Google Drive for spreadsheets",
        stream=True,
    )

    # Example 3: Read a Google Doc and summarize
    # read_only_agent.print_response(
    #     "Read the Google Drive file with ID <FILE_ID> and summarize it",
    #     stream=True,
    # )

    # Example 4: Search files in a specific folder
    # read_only_agent.print_response(
    #     "What files are inside the folder called 'Projects'?",
    #     stream=True,
    # )

    # Example 6: Upload a file (requires full_drive_agent)
    # full_drive_agent.print_response(
    #     "Upload the file at /path/to/document.pdf to my Google Drive",
    #     stream=True,
    # )

    # Example 7: Download a file (requires full_drive_agent)
    # full_drive_agent.print_response(
    #     "Download the file 'report.csv' from my Google Drive to /tmp/report.csv",
    #     stream=True,
    # )
