"""Glass Schedule Meeting — Calendar + People + Meet combined agent.

Enterprise use case: Schedule a meeting by:
1. Looking up attendee emails from names
2. Finding available time slots
3. Creating the calendar event with Meet link

Uses HITL confirmation for create_event.

Note: GoogleMeetTools creates standalone Meet spaces. For calendar events with
Meet links, use GoogleCalendarTools.create_event with conferenceData — the
calendar API handles Meet link generation automatically.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.meet import GoogleMeetTools
from agno.tools.google.people import GooglePeopleTools

SCHEDULING_INSTRUCTIONS = """\
You are a meeting scheduling assistant. When asked to schedule a meeting:

1. **Resolve Names** — If given names instead of emails, look them up in contacts/directory
2. **Check Availability** — Find free time slots for all attendees
3. **Create Event** — Create the calendar event with:
   - Clear title
   - All attendees
   - Google Meet link for video calls
   - Appropriate duration (default 30min for 1:1, 60min for groups)

Always confirm the meeting details before creating. If attendees have conflicts, suggest alternatives.
"""

db = SqliteDb(db_file="glass_scheduling.db")

agent = Agent(
    name="MeetingScheduler",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GooglePeopleTools(
            search_contacts=True,
            list_directory_people=True,
        ),
        GoogleCalendarTools(
            list_events=True,
            find_available_slots=True,
            check_availability=True,
            create_event=True,
            store_token_in_db=True,
            requires_confirmation_tools=["create_event"],
        ),
        GoogleMeetTools(
            create_meeting_space=True,
            requires_confirmation_tools=["create_meeting_space"],
        ),
    ],
    instructions=SCHEDULING_INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Schedule a 30 minute meeting with John Smith tomorrow afternoon to discuss Q3 planning",
        user_id="mustafa@agno.com",
        stream=True,
    )
