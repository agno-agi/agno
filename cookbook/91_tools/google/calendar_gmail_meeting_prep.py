"""
Meeting Prep Agent (Calendar + Gmail)
=====================================
Prepares you for upcoming meetings by combining calendar and email context.

Workflow:
1. Fetches your next meeting (or a specific one) from Google Calendar
2. Identifies attendees and their RSVP status
3. Searches Gmail for recent threads involving those attendees
4. Produces a structured prep brief: who's coming, recent topics, open threads

Key concepts:
- Two toolkits on one agent: GoogleCalendarTools + GmailTools
- Multi-step reasoning: calendar lookup -> attendee extraction -> email search
- output_schema: structured meeting prep brief
- add_datetime_to_context: agent knows "now" for finding the next meeting

Setup:
1. Enable both Calendar API and Gmail API at https://console.cloud.google.com
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent (grants both Calendar + Gmail access)
   The same token.json works for both APIs if scopes include both.
"""

from typing import List, Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from pydantic import BaseModel, Field


class AttendeeInfo(BaseModel):
    name: str = Field(..., description="Attendee name or email")
    rsvp: Literal["accepted", "declined", "tentative", "needsAction", "unknown"] = (
        Field("unknown", description="RSVP status from calendar")
    )
    recent_email_subjects: List[str] = Field(
        default_factory=list,
        description="Subjects of recent emails from/to this person (last 7 days)",
    )


class OpenThread(BaseModel):
    subject: str = Field(..., description="Email thread subject")
    participants: List[str] = Field(..., description="People in the thread")
    last_message_date: str = Field(..., description="Date of last message")
    summary: str = Field(..., description="One-sentence summary of the thread")
    needs_response: bool = Field(
        False, description="Whether the last message is waiting for user's reply"
    )


class MeetingPrepBrief(BaseModel):
    meeting_title: str = Field(..., description="Meeting title from calendar")
    meeting_time: str = Field(..., description="Start time in human-readable format")
    duration_minutes: int = Field(..., description="Duration in minutes")
    location: Optional[str] = Field(None, description="Location or video call link")
    attendees: List[AttendeeInfo] = Field(
        default_factory=list, description="Attendee details with email context"
    )
    open_threads: List[OpenThread] = Field(
        default_factory=list,
        description="Active email threads with meeting attendees",
    )
    talking_points: List[str] = Field(
        default_factory=list,
        description="Suggested talking points based on recent email topics",
    )
    prep_summary: str = Field(
        ..., description="2-3 sentence overview of what to expect in this meeting"
    )


agent = Agent(
    name="Meeting Prep Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GoogleCalendarTools(
            create_event=False,
            update_event=False,
            delete_event=False,
        ),
        GmailTools(
            include_tools=[
                "search_emails",
                "get_emails_by_context",
                "get_thread",
            ]
        ),
    ],
    instructions=[
        "When asked to prep for a meeting:",
        "1. Use list_events to find the meeting, then get_event_attendees for RSVP details.",
        "2. For each attendee, use search_emails to find recent emails (last 7 days).",
        "3. If relevant threads exist, use get_thread to read the full conversation.",
        "4. Identify open threads where the last message needs the user's reply.",
        "5. Generate talking points from email topics related to the meeting subject.",
        "6. Write a prep_summary covering: who is attending, key open topics, any pending replies.",
        "Keep email searches focused -- search by attendee email, not by name.",
    ],
    output_schema=MeetingPrepBrief,
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Prep me for my next meeting -- who's attending and what have we been discussing over email?",
        stream=True,
    )

    # Prep for a specific meeting
    # agent.print_response(
    #     "Prep me for the 'Q1 Planning' meeting this week",
    #     stream=True,
    # )

    # Prep for all meetings today
    # agent.print_response(
    #     "Give me a prep brief for each of my meetings today",
    #     stream=True,
    # )
