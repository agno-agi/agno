"""
This example demonstrates how to use the Google Drive Toolkit, allowing your Agents to interact with Google Drive.

Google Drive Toolkit can be used to read, create, update and duplicate Google Drive files.

Setup instructions for the Auth flow:
1. Go to the Google Cloud Console.
2. Navigate to "APIs & Services" > "Credentials".
3. Select your OAuth 2.0 Client ID from the list.
4. In the "Authorized redirect URIs" section, click "Add URI".
5. Enter the complete redirect URI, with the port number included (e.g., http://localhost:5050).
6. Click "Save" to apply the changes.

After setup, remember to set the GOOGLE_AUTH_PORT and GOOGLE_CLOUD_QUOTA_PROJECT_ID environment variables.

The Tool Kit Functions are:
1. List Files
2. Upload File
3. Download File
"""

from agno.agent import Agent
from agno.tools.google_drive import GoogleDriveTools

google_drive_tools = GoogleDriveTools(auth_port=5050)

agent = Agent(
    tools=[google_drive_tools],
    instructions=[
        "You help users interact with Google Drive using tools that use the Google Drive API",
        "Before asking for file details, first attempt the operation as the user may have already configured the credentials in the constructor",
    ],
)

# Example 1: List files in Google Drive
agent.print_response("Please list the files in my Google Drive")

# Example 2: Upload a file to Google Drive
# file_path = ...
# agent.print_response(
#     "Please upload this file to my Google Drive", files=[File(path=file_path)]
# )

# Example 3: Download a file from Google Drive
# agent.print_response(
#     "Please download the 'test.txt' file from my Google Drive. It's in the 'test_files' folder."
# )
