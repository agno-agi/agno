"""
Calendar Meeting Scheduler
===========================
Finds a time that works for all attendees and creates the meeting.

Multi-step workflow: check_availability across attendees, find overlapping
free slots, present options, then create_event with the chosen time.

Key concepts:
- check_availability: FreeBusy API for multi-person scheduling
- find_available_slots: user's own free windows
- create_event: with attendees, Google Meet link, and reminders
- Multi-step agent reasoning: query -> analyze -> propose -> create

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Calendar API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools
from pydantic import BaseModel, Field


class TimeSlot(BaseModel):
    start: str = Field(..., description="Slot start in ISO format")
    end: str = Field(..., description="Slot end in ISO format")
    duration_minutes: int = Field(..., description="Duration in minutes")


class SchedulingResult(BaseModel):
    attendees: List[str] = Field(..., description="Email addresses of all attendees")
    available_slots: List[TimeSlot] = Field(
        default_factory=list, description="Time slots where all attendees are free"
    )
    chosen_slot: Optional[TimeSlot] = Field(
        None, description="The slot that was selected for the meeting"
    )
    event_created: bool = Field(False, description="Whether the event was created")
    event_id: Optional[str] = Field(None, description="Created event ID if applicable")
    notes: str = Field(..., description="Summary of scheduling outcome")


agent = Agent(
    name="Meeting Scheduler",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GoogleCalendarTools(
            quick_add_event=True,
        )
    ],
    description="You are a meeting scheduling assistant that finds times that work for everyone.",
    instructions=[
        "When asked to schedule a meeting with attendees:",
        "1. Use check_availability to find when all attendees are free.",
        "2. Cross-reference with find_available_slots for the user's own free windows.",
        "3. Present the best 3 available slots (prefer morning, avoid lunch 12-1pm).",
        "4. Create the event with the first available slot unless the user specifies otherwise.",
        "Always add a Google Meet link for remote meetings (set add_google_meet=True).",
        "Set a 10-minute popup reminder by default.",
    ],
    output_schema=SchedulingResult,
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Schedule a 30-minute meeting with alice@company.com and bob@company.com "
        "sometime this week. Add a Google Meet link.",
        stream=True,
    )

    # Schedule with specific constraints
    # agent.print_response(
    #     "Find a 1-hour slot for a team review with alice@company.com, bob@company.com, "
    #     "and carol@company.com. Must be in the afternoon (after 2pm) this week.",
    #     stream=True,
    # )

    # Quick scheduling without availability check
    # agent.print_response(
    #     "Quick add: Design review with the team Friday at 3pm for 45 minutes",
    #     stream=True,
    # )
