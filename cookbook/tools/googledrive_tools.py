"""
Google Drive Toolkit example for Agno (Agent-driven).

Demonstrates:
1. Agent lists files whose name starts with "report" (max 10).

Requires:
- credentials.json or env vars for OAuth
- Authorised redirect URI matching oauth_port in Google Cloud Console
Example: http://localhost:8080/flowName=GeneralOAuthFlow
"""

from agno.agent import Agent
from agno.tools.googledrive import GoogleDriveTools

# --- Initialize Google Drive Tools ---
google_drive_tools = GoogleDriveTools(
    oauth_port=8080  # Change if needed
)

# Create Agent with debug and monitoring
agent = Agent(
    tools=[google_drive_tools],
    show_tool_calls=True,
    markdown=True,
    instructions=[
        "You help users interact with Google Drive using the Google Drive API.",
        "You can list, search, download, upload, and delete files as needed.",
    ],
)

# Run all tasks through Agent
agent.print_response("""
List up to 10 files in my Google Drive whose name starts with 'report'
""")
