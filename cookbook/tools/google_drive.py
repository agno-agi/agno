"""

Google Drive Toolkit can be used to read, create, update and duplicate Google Drive files.
Example Redirect URI : http://localhost:5050/
Example Auth PORT: 5050
Note: Add the complete auth URL as an Authorised redirect URIs for the Client ID in the Google Cloud Console.

Instructions to add Authorised redirect URIs:

1. Go to the Google Cloud Console.
2. Navigate to "APIs & Services" > "Credentials".
3. Select your OAuth 2.0 Client ID from the list.
4. In the "Authorized redirect URIs" section, click "Add URI".
5. Enter the complete redirect URI, with the port number included (e.g., http://localhost:5050).
6. Click "Save" to apply the changes.


You need to pass the same port number in the toolkit constructor.

The Tool Kit Functions are: 
1. List Files
2. Upload File
3. Download File
e.g for Localhost and port 5050: http://localhost:5050 and pass the oauth_port to the toolkit
"""


from agno.agent import Agent
from agno.tools.google_drive import GoogleDriveTools

google_drive_tools = GoogleDriveTools(oauth_port=5050) 

agent = Agent(
    tools=[google_drive_tools],
    instructions=[
        "You help users interact with Google Drive using tools that use the Google Drive API",
        "Before asking for file details, first attempt the operation as the user may have already configured the credentials in the constructor",
    ],
)
agent.print_response("Please list the files in my Google Drive")

