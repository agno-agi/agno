"""
Zoom Tools Example - Demonstrates how to use the Zoom toolkit for meeting management.

This example shows how to:
1. Set up authentication with Zoom API
2. Initialize the ZoomTools with proper credentials
3. Create an agent that can manage Zoom meetings
4. Use various Zoom API functionalities through natural language

Prerequisites:
-------------
1. Create a Server-to-Server OAuth app in Zoom Marketplace:
   - Visit https://marketplace.zoom.us/
   - Create a new app. Go to Develop -> Build App -> Server-to-Server OAuth.
   - Add required scopes:
     * meeting:write:admin
     * meeting:read:admin
     * cloud_recording:read:admin
   - Copy Account ID, Client ID, and Client Secret

2. Set environment variables:
   export ZOOM_ACCOUNT_ID=your_account_id
   export ZOOM_CLIENT_ID=your_client_id
   export ZOOM_CLIENT_SECRET=your_client_secret

Features:
---------
- Schedule new meetings
- Get meeting details
- List all meetings
- Get upcoming meetings
- Delete meetings
- Get meeting recordings

Usage:
------
Run this script with proper environment variables set to interact with
the Zoom API through natural language commands.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.zoom import ZoomTools

# Get environment variables
ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID")
CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")

# Initialize Zoom tools with credentials
zoom_tools = ZoomTools(
    account_id=ACCOUNT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
)

# Create an agent with Zoom capabilities
agent = Agent(
    name="Zoom Meeting Manager",
    agent_id="zoom-meeting-manager",
    model=OpenAIChat(id="gpt-4"),
    tools=[zoom_tools],
    markdown=True,
    debug_mode=True,
    show_tool_calls=True,
    instructions=[
        "You are an expert at managing Zoom meetings using the Zoom API.",
        "You can:",
        "1. Schedule new meetings (schedule_meeting)",
        "2. Get meeting details (get_meeting)",
        "3. List all meetings (list_meetings)",
        "4. Get upcoming meetings (get_upcoming_meetings)",
        "5. Delete meetings (delete_meeting)",
        "6. Get meeting recordings (get_meeting_recordings)",
        "",
        "For recordings, you can:",
        "- Retrieve recordings for any past meeting using the meeting ID",
        "- Include download tokens if needed",
        "- Get recording details like duration, size, download link and file types",
        "",
        "Guidelines:",
        "- Use ISO 8601 format for dates (e.g., '2024-12-28T10:00:00Z')",
        "- Accept and use user's timezone (e.g., 'America/New_York', 'Asia/Tokyo', 'UTC')",
        "- If no timezone is specified, default to UTC",
        "- Ensure meeting times are in the future",
        "- Provide meeting details after scheduling (ID, URL, time)",
        "- Handle errors gracefully",
        "- Confirm successful operations",
    ],
)

# Example usage - uncomment the ones you want to try
agent.print_response(
    "Schedule a meeting titled 'Team Sync' for tomorrow at 2 PM UTC for 45 minutes"
)

# More examples (uncomment to use):
# agent.print_response("What meetings do I have coming up?")
# agent.print_response("List all my scheduled meetings")
# agent.print_response("Get details for my most recent meeting")
# agent.print_response("Get the recordings for my last team meeting")
# agent.print_response("Delete the meeting titled 'Team Sync'")
# agent.print_response("Schedule daily standup meetings for next week at 10 AM UTC")
