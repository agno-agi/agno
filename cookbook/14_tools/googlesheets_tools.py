"""

Google Sheets Toolkit can be used to read, create, update and duplicate Google Sheets.

Example spreadsheet: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/
The ID is the URL of the spreadsheet and the range is the sheet name and the range of cells to read.

If you'd like to use a service account for access to Google Sheets, provide the absolute path
to the service account file either using the service_account_path arg in the GoogleSheetsTools
constructor or using a GOOGLE_SERVICE_ACCOUNT_FILE environment variable.

Note: Add the complete auth URL as an Authorised redirect URIs for the Client ID in the Google Cloud Console.

e.g for Localhost and port 8080: http://localhost:8080/flowName=GeneralOAuthFlow and pass the oauth_port to the toolkit

"""

from agno.agent import Agent
from agno.tools.googlesheets import GoogleSheetsTools

SAMPLE_SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
SAMPLE_RANGE_NAME = "Class Data!A2:E"

google_sheets_tools = GoogleSheetsTools(
    spreadsheet_id=SAMPLE_SPREADSHEET_ID,
    spreadsheet_range=SAMPLE_RANGE_NAME,
    oauth_port=8080,  # or any other port
)

agent = Agent(
    tools=[google_sheets_tools],
    instructions=[
        "You help users interact with Google Sheets using tools that use the Google Sheets API",
        "Before asking for spreadsheet details, first attempt the operation as the user may have already configured the ID and range in the constructor",
    ],
)
agent.print_response("Please tell me about the contents of the spreadsheet")
