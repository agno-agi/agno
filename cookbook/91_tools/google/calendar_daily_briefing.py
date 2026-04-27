"""
Calendar Daily Briefing
=======================
Summarizes today's schedule into a structured briefing with meeting prep notes.

The agent fetches today's events, classifies each by type (meeting, focus time,
personal), identifies gaps, and flags conflicts or back-to-back meetings.

Key concepts:
- output_schema: structured briefing matching DailyBriefing model
- add_datetime_to_context: agent knows today's date for time-aware queries
- get_event + list_events: fetches overview then drills into details

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Calendar API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools
from pydantic import BaseModel, Field


class MeetingItem(BaseModel):
    title: str = Field(..., description="Event title")
    start_time: str = Field(..., description="Start time (HH:MM format)")
    end_time: str = Field(..., description="End time (HH:MM format)")
    duration_minutes: int = Field(..., description="Duration in minutes")
    category: Literal["meeting", "focus_time", "personal", "travel", "other"] = Field(
        ..., description="Event category based on title and attendees"
    )
    attendee_count: int = Field(0, description="Number of attendees")
    location: Optional[str] = Field(None, description="Event location or video link")
    prep_note: Optional[str] = Field(
        None, description="One-line prep note if this is a meeting with others"
    )


class DailyBriefing(BaseModel):
    date: str = Field(..., description="Today's date in YYYY-MM-DD format")
    total_events: int = Field(..., description="Total number of events today")
    total_meeting_hours: float = Field(..., description="Total hours in meetings")
    free_hours: float = Field(..., description="Estimated free hours between 9am-6pm")
    events: List[MeetingItem] = Field(
        default_factory=list, description="All events in chronological order"
    )
    conflicts: List[str] = Field(
        default_factory=list,
        description="Overlapping events or back-to-back warnings",
    )
    summary: str = Field(..., description="2-3 sentence overview of the day")


agent = Agent(
    name="Daily Briefing Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GoogleCalendarTools(
            create_event=False,
            update_event=False,
            delete_event=False,
        )
    ],
    instructions=[
        "Fetch today's events and classify each as meeting, focus_time, personal, travel, or other.",
        "A 'meeting' has 2+ attendees. 'focus_time' is a solo block. 'personal' is non-work.",
        "Calculate total meeting hours and free hours (9am-6pm minus events).",
        "Flag conflicts: overlapping events or back-to-back meetings with no gap.",
        "Add a prep_note for meetings: mention the key attendee or agenda if visible.",
        "Write a 2-3 sentence summary highlighting the busiest part of the day.",
    ],
    output_schema=DailyBriefing,
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Give me my daily briefing for today",
        stream=True,
    )

    # Briefing for a specific date
    # agent.print_response(
    #     "Give me a briefing for next Monday",
    #     stream=True,
    # )
