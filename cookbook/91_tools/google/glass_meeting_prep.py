"""Glass Meeting Prep — Calendar + Gmail + People + Drive combined agent.

Enterprise use case: Prepare for an upcoming meeting by gathering:
1. Meeting details and attendees
2. Recent email threads with attendees
3. Attendee contact info and roles
4. Relevant documents from Drive

Uses DB token storage for multi-user support.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.people import GooglePeopleTools

MEETING_PREP_INSTRUCTIONS = """\
You are a meeting preparation assistant. When asked to prep for a meeting:

1. **Meeting Context** — Get the meeting details, attendees, and agenda
2. **Attendee Lookup** — Look up each attendee in contacts/directory to find their role/title
3. **Recent Threads** — Search emails for recent conversations with the attendees
4. **Relevant Docs** — Search Drive for documents related to the meeting topic or attendees
5. **Prep Notes** — Summarize key context and suggest talking points

Be thorough but concise. Cite sources (email subjects, doc names).
"""

db = SqliteDb(db_file="glass_meeting_prep.db")

agent = Agent(
    name="MeetingPrep",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GoogleCalendarTools(
            list_events=True,
            get_event=True,
            store_token_in_db=True,
        ),
        GmailTools(
            search_emails=True,
            get_emails_from_user=True,
            get_emails_by_thread=True,
            store_token_in_db=True,
        ),
        GooglePeopleTools(
            search_contacts=True,
            list_directory_people=True,
        ),
        GoogleDriveTools(
            search_files=True,
            read_file=True,
            store_token_in_db=True,
        ),
    ],
    instructions=MEETING_PREP_INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Prep me for my next meeting today",
        user_id="mustafa@agno.com",
        stream=True,
    )
