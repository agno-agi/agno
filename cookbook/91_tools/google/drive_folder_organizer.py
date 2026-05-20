"""
Drive Folder Organizer
======================
Lists folder contents and helps organize files by uploading to specific locations.

Combines read tools (list_files, search_files) with write tools (upload_file)
to give the agent a complete view of Drive structure.

Key concepts:
- list_files with folder queries: Browse Drive like a file system
- upload_file: Upload local files to Drive (disabled by default, enabled here)
- Drive query syntax: "'<FOLDER_ID>' in parents" to scope to a folder

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools

agent = Agent(
    name="Drive Organizer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools(upload_file=True, download_file=True)],
    instructions=[
        "Help the user explore and organize their Google Drive.",
        "When listing folders, show structure as an indented tree.",
        "Before uploading, confirm the file path and destination with the user.",
        "Before downloading, confirm the destination path.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # List top-level folders
    agent.print_response(
        "List all folders in the root of my Google Drive",
        stream=True,
    )

    # Explore a specific folder
    # agent.print_response(
    #     "What files are inside the folder called 'Projects'?",
    #     stream=True,
    # )

    # Upload to Drive
    # agent.print_response(
    #     "Upload /tmp/notes.txt to my Google Drive",
    #     stream=True,
    # )

    # Download from Drive
    # agent.print_response(
    #     "Download the file named 'meeting-notes.docx' to /tmp/",
    #     stream=True,
    # )
