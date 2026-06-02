"""Glass Email with Context — Gmail + People + Drive combined agent.

Enterprise use case: Draft or send emails with full context:
1. Look up recipient from name
2. Find recent email threads with them
3. Attach relevant Drive documents
4. Draft email matching user's tone

Uses HITL confirmation for send_email.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.people import GooglePeopleTools

EMAIL_INSTRUCTIONS = """\
You are an email drafting assistant. When asked to write or send an email:

1. **Resolve Recipient** — If given a name, look up their email in contacts/directory
2. **Find Context** — Search for recent email threads with the recipient to understand the relationship and tone
3. **Find Attachments** — If the email references documents, search Drive and offer to attach them
4. **Draft Email** — Write a professional email that:
   - Matches the user's typical tone (based on sent emails)
   - Includes context from prior conversations if relevant
   - Has a clear call-to-action

Always show the draft before sending. For sensitive emails, summarize what you're about to send.
"""

db = SqliteDb(db_file="glass_email.db")

agent = Agent(
    name="EmailAssistant",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GooglePeopleTools(
            search_contacts=True,
            list_directory_people=True,
        ),
        GmailTools(
            search_emails=True,
            get_emails_from_user=True,
            get_emails_by_thread=True,
            create_draft_email=True,
            send_email=True,
            store_token_in_db=True,
            requires_confirmation_tools=["send_email"],
        ),
        GoogleDriveTools(
            search_files=True,
            read_file=True,
            store_token_in_db=True,
        ),
    ],
    instructions=EMAIL_INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Draft an email to Sarah about the Q3 budget report we discussed last week",
        user_id="mustafa@agno.com",
        stream=True,
    )
