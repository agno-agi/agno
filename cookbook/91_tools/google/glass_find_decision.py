"""Glass Find Decision — Gmail + Drive + Meet combined agent.

Enterprise use case: Answer "why did we decide X?" by searching:
1. Email threads discussing the decision
2. Meeting transcripts where it was discussed
3. Documents (PRDs, RFCs, meeting notes) in Drive

Returns a timeline with citations.

Note on Meet transcripts:
- Requires Workspace admin to enable transcription at the org level
- Someone must manually start transcription during the call
- Only accessible for meetings where the user was the organizer
- Transcripts take several minutes to generate after meeting ends
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools

RESEARCH_INSTRUCTIONS = """\
You are a decision research assistant. When asked "why did we decide X?" or similar:

1. **Search Emails** — Find email threads discussing the topic, decision, or alternatives
2. **Search Drive** — Find PRDs, RFCs, meeting notes, or decision docs related to the topic
3. **Search Meetings** — Look for meeting recordings/transcripts where this was discussed
4. **Build Timeline** — Construct a timeline of:
   - When it was first discussed
   - What alternatives were considered
   - Who made the final decision
   - Why that decision was made

Always cite your sources with links. If you can't find the decision context, say so clearly.
"""

db = SqliteDb(db_file="glass_research.db")

agent = Agent(
    name="DecisionResearcher",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GmailTools(
            search_emails=True,
            get_emails_by_thread=True,
            store_token_in_db=True,
        ),
        GoogleDriveTools(
            search_files=True,
            read_file=True,
            store_token_in_db=True,
        ),
        GoogleMeetTools(
            list_conference_records=True,
            list_transcripts=True,
            list_transcript_entries=True,
        ),
    ],
    instructions=RESEARCH_INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Why did we decide to use PostgreSQL instead of MongoDB for the user service?",
        user_id="mustafa@agno.com",
        stream=True,
    )
