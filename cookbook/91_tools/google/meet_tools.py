"""
Google Meet Agent
=================
Agent that creates meeting spaces and reads conference records, participants,
and transcripts using the Google Meet API.

Setup:
1. pip install agno[google_meet]
2. Enable the Google Meet API in Google Cloud Console
3. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID
   OR provide credentials.json in the working directory
4. First run opens a browser for OAuth consent
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.meet import GoogleMeetTools

agent = Agent(
    name="Google Meet Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[GoogleMeetTools()],
    instructions=[
        "You help users create Google Meet spaces and review past meeting data.",
        "When creating a meeting, share the meeting_uri so the user can join.",
        "When summarizing a past meeting, use list_conference_records to find it,",
        "then list_participants and list_transcripts to gather the details.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

agent.print_response(
    "Create a new Google Meet space and give me the link to share.",
    stream=True,
)

# Uncomment to test more tools:
# agent.print_response(
#     "List my last 5 Google Meet conferences and show participants for the most recent one.",
#     stream=True,
# )
#
# agent.print_response(
#     "Find my most recent Meet with transcripts available and summarize what was discussed.",
#     stream=True,
# )
