"""Glass Slack Bot — Test Google toolkits via Slack.

Run with:
    .venvs/demo/bin/python cookbook/91_tools/google/glass_slack_bot.py

Uses credentials from:
    - /Users/coolm/Developer/glass/.env (Google OAuth)
    - /Users/coolm/Developer/pal/.env (Mustafa's PAL Slack)

ngrok URL: https://paraphrastic-sang-ingenuous.ngrok-free.dev
Slack Event URL: https://paraphrastic-sang-ingenuous.ngrok-free.dev/slack/events
Google OAuth Callback: https://paraphrastic-sang-ingenuous.ngrok-free.dev/google/oauth/callback
"""

from os import getenv
from pathlib import Path

from dotenv import load_dotenv

# Load Glass env (Google OAuth creds)
load_dotenv(Path.home() / "Developer/glass/.env")
# Load PAL env (Mustafa's PAL Slack creds)
load_dotenv(Path.home() / "Developer/pal/.env")

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google import GoogleAuth, OAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools
from agno.tools.google.people import GooglePeopleTools
from agno.tools.google.tasks import GoogleTasksTools

GLASS_INSTRUCTIONS = """\
You are Glass, an enterprise assistant with access to Google Workspace.

You can help with:
- **Calendar**: List events, check availability, schedule meetings
- **Email**: Search emails, read threads, draft/send emails
- **Contacts**: Look up people by name, find their email/role
- **Drive**: Search files, read documents
- **Tasks**: List task lists, view tasks
- **Meet**: Create meeting spaces, view past conference transcripts

When asked to do something:
1. Resolve names to emails using People/Contacts when needed
2. Search for relevant context (emails, docs) before acting
3. Confirm before sending emails or creating events
4. Be concise — Slack messages should be scannable

For daily briefings, include: today's meetings, priority emails, due tasks.
For meeting prep, include: attendees, recent threads, relevant docs.

If a user hasn't authenticated with Google yet, you'll receive an OAuth URL.
Share that link with the user so they can authorize access.
"""

db = SqliteDb(db_file="tmp/glass_slack.db")

# Multi-user OAuth config — sends links back instead of opening browser
# Use Web OAuth credentials (have ngrok redirect URI registered)
auth = GoogleAuth(
    client_id=getenv("GOOGLE_CLIENT_ID_WEB") or getenv("GOOGLE_CLIENT_ID"),
    client_secret=getenv("GOOGLE_CLIENT_SECRET_WEB") or getenv("GOOGLE_CLIENT_SECRET"),
    redirect_uri=getenv(
        "GOOGLE_REDIRECT_URI",
        "https://paraphrastic-sang-ingenuous.ngrok-free.dev/google/oauth/callback",
    ),
    oauth_config=OAuthConfig(
        db=db,
        store_tokens=True,
        encrypt_tokens=True,
        enable_multi_user_oauth=True,
    ),
)

glass_agent = Agent(
    name="Glass",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GmailTools(
            auth=auth,
            include_tools=[
                "get_latest_emails",
                "get_unread_emails",
                "search_emails",
                "get_emails_by_thread",
                "create_draft_email",
                "send_email",
            ],
            requires_confirmation_tools=["send_email"],
        ),
        GoogleCalendarTools(
            auth=auth,
            include_tools=[
                "list_events",
                "get_event",
                "find_available_slots",
                "check_availability",
                "create_event",
            ],
            requires_confirmation_tools=["create_event"],
        ),
        GooglePeopleTools(
            search_contacts=True,
            list_directory_people=True,
        ),
        GoogleDriveTools(
            auth=auth,
            include_tools=["search_files", "read_file"],
        ),
        GoogleTasksTools(
            list_task_lists=True,
            list_tasks=True,
        ),
        GoogleMeetTools(
            create_meeting_space=True,
            list_conference_records=True,
            list_transcripts=True,
            list_transcript_entries=True,
            requires_confirmation_tools=["create_meeting_space"],
        ),
    ],
    instructions=GLASS_INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
)

agent_os = AgentOS(
    agents=[glass_agent],
    interfaces=[
        Slack(
            agent=glass_agent,
            reply_to_mentions_only=True,
            token=getenv("MUSTAFAS_PAL_SLACK_TOKEN"),
            signing_secret=getenv("MUSTAFAS_PAL_SIGNING_SECRET"),
        )
    ],
)
app = agent_os.get_app()

# Mount OAuth callback router for Google authentication
app.include_router(auth.create_router())

if __name__ == "__main__":
    agent_os.serve(app="glass_slack_bot:app", port=7778, reload=True)
