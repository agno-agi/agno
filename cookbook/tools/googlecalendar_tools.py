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
"""

from agno.agent import Agent
from agno.tools.googlecalendar import GoogleCalendarTools

agent = Agent(
    tools=[
        GoogleCalendarTools(
            credentials_path="./credentials.json",  # Path to your downloaded OAuth credentials
        )
    ],
    # show_tool_calls=True,
    debug_mode=True,
    instructions=[
        """
You are a scheduling assistant.
You should help users to perform these actions in their Google calendar:
    - get their scheduled events from a certain date and time
    - create events based on provided details
    - update existing events
    - delete events
    - find available time slots for scheduling
"""
    ],
    add_datetime_to_instructions=True,
)

# Basic examples
print("Getting today's events...")
agent.print_response("Give me the list of today's events", markdown=True)

print("\nCreating a test event...")
agent.print_response(
    "create an event tomorrow from 9am to 10am, make the title as 'Team Meeting' and description as 'Weekly team sync'",
    markdown=True,
)

print("\nFinding available time slots for tomorrow...")
agent.print_response(
    "Find available 1-hour time slots for tomorrow between 9 AM and 5 PM",
    markdown=True,
)

# Advanced examples (uncomment to test)

# print("\nUpdating the event...")
# agent.print_response(
#     "update the 'Team Meeting' event today to run from 5pm to 7pm and change description to 'Extended team sync'",
#     markdown=True
# )

# print("\nGetting all events for the week...")
# agent.print_response("Show me all events for this week", markdown=True)

# print("\nDeleting the test event...")
# agent.print_response("delete the 'Team Meeting' event", markdown=True)

# Example using token-based authentication (for apps that already have tokens)
# from agno.tools.googlecalendar import GoogleCalendarTokenTools
# agent_with_token = Agent(
#     tools=[GoogleCalendarTokenTools(access_token="your_access_token_here")],
#     show_tool_calls=True,
# )
