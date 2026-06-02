"""Glass Daily Briefing — Gmail + Calendar + Tasks combined agent.

Enterprise use case: Start-of-day briefing that shows:
1. Today's meetings with attendees
2. Priority unread emails
3. Overdue and due-today tasks
4. Action items extracted from recent emails

Uses DB token storage for multi-user support.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.tasks import GoogleTasksTools

BRIEFING_INSTRUCTIONS = """\
You are a daily briefing assistant. When asked for a briefing, provide:

1. **Today's Schedule** — List meetings with times, attendees, and meeting links
2. **Priority Emails** — Show unread emails that need attention (from important senders or with urgent keywords)
3. **Tasks Due** — List overdue tasks and tasks due today
4. **Action Items** — Extract any action items from recent emails

Keep it scannable. Use bullet points. Lead with the most important items.
"""

db = SqliteDb(db_file="glass_briefing.db")

agent = Agent(
    name="DailyBriefing",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GmailTools(
            get_latest_emails=True,
            get_unread_emails=True,
            search_emails=True,
            store_token_in_db=True,
        ),
        GoogleCalendarTools(
            list_events=True,
            get_event=True,
            store_token_in_db=True,
        ),
        GoogleTasksTools(
            list_task_lists=True,
            list_tasks=True,
        ),
    ],
    instructions=BRIEFING_INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Give me my daily briefing for today",
        user_id="mustafa@agno.com",
        stream=True,
    )
