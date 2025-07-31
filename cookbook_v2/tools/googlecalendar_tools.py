import datetime
import os

from agno.agent import Agent
from agno.models.mistral import MistralChat
from agno.tools.googlecalendar import GoogleCalendarTools

"""
Steps to get the Google OAuth Credentials (Reference : https://developers.google.com/calendar/api/quickstart/python)

1. Enable Google Calender API
    - Go To https://console.cloud.google.com/apis/enableflow?apiid=calendar-json.googleapis.com
    - Select Project and Enable The API

2. Go To API & Service -> OAuth Consent Screen

3.Select User Type .
    - If you are Google Workspace User select Internal
    - Else Select External

4.Fill in the app details (App name, logo, support email, etc.).

5. Select Scope
    - Click on Add or Remove Scope
    - Search for Google Calender API (Make Sure you've enabled Google calender API otherwise scopes wont be visible)
    - Select Scopes Accordingly
        - From the dropdown check on /auth/calendar scope
    - Save and Continue


6. Adding Test User
    - Click Add Users and enter the email addresses of the users you want to allow during testing.
    - NOTE : Only these users can access the app's OAuth functionality when the app is in "Testing" mode.
    If anyone else tries to authenticate, they'll see an error like: "Error 403: access_denied."
    - To make the app available to all users, you'll need to move the app's status to "In Production.".
    Before doing so, ensure the app is fully verified by Google if it uses sensitive or restricted scopes.
    - Click on Go back to Dashboard


7. Generate OAuth 2.0 Client ID
    - Go To Credentials
    - Click on Create Credentials -> OAuth Client ID
    - Select Application Type as Desktop app
    - Download JSON

8. Using Google Calender Tool
    - Pass the Path of downloaded credentials as credentials_path to Google Calender tool
    - token_path is an Optional parameter where you have to provide the path to create token.json file.
    - The token.json file is used to store the user's access and refresh tokens and is automatically created during the authorization flow if it doesn't already exist.
    - If token_path is not explicitly provided, the file will be created in the default location which is your current working directory
    - If you choose to specify token_path, please ensure that the directory you provide has write access, as the application needs to create or update this file during the authentication process.
"""


try:
    from tzlocal import get_localzone_name
except (ModuleNotFoundError, ImportError):
    raise ImportError("`tzlocal not found` install using `pip install tzlocal`")

agent = Agent(
    tools=[GoogleCalendarTools(credentials_path="<PATH_TO_YOUR_CREDENTIALS_FILE>")],
    show_tool_calls=True,
    instructions=[
        f"""
You are scheduling assistant . Today is {datetime.datetime.now()} and the users timezone is {get_localzone_name()}.
You should help users to perform these actions in their Google calendar :
    - get their scheduled events from a certain date and time
    - create events based on provided details
"""
    ],
    model=MistralChat(api_key=os.getenv("MISTRAL_API_KEY")),
    add_datetime_to_instructions=True,
)

agent.print_response("Give me the list of todays events", markdown=True)

# agent.print_response(
#     "create an event today from 5pm to 6pm, make the title as test event v1 and description as this is a test event", markdown=True)
