"""
Gmail Inbox Triage
==================
A personal inbox triage agent that learns your preferences across sessions.

Combines Gmail tools with the Learning Machine to build persistent memory:
- Learns your communication tone and style
- Remembers frequent contacts and relationships
- Adapts drafts to match your writing patterns
- Uses date awareness for time-relative queries ("last week", "this month")

Key concepts:
- LearningMachine with UserMemoryConfig: Persistent preference storage
- add_datetime_to_context: Date-aware email queries without unix timestamps
- get_thread + get_message: Full context before drafting
- Multi-session learning: Agent improves with each interaction

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. Start PostgreSQL: cookbook/scripts/run_pgvector.sh
5. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    name="Inbox Triage Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(download_attachment=True, archive_email=True)],
    db=db,
    learning=LearningMachine(
        user_memory=UserMemoryConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
    instructions=[
        "You are a personal email assistant that learns the user's preferences over time.",
        "Before drafting any reply, read the full thread with get_thread to understand context.",
        "Match the user's tone: if they write casually, draft casually. If formal, match it.",
        "When the user corrects a draft or gives style feedback, remember it for next time.",
        "For date-based queries, use get_emails_by_date with YYYY/MM/DD format.",
        "When asked about attachments, use get_message to find attachment IDs, then download_attachment.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    user_id = "user@example.com"

    # Session 1: The agent learns your style
    print("\n" + "=" * 60)
    print("SESSION 1: Agent learns your communication style")
    print("=" * 60 + "\n")

    agent.print_response(
        "Find my most recent email thread and draft a reply. "
        "Keep it short and direct -- I don't like fluffy language.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    # Show what the agent learned
    if agent.learning_machine and agent.learning_machine.user_memory_store:
        print("\n--- Learned memories ---")
        agent.learning_machine.user_memory_store.print(user_id=user_id)

    # Session 2: Agent recalls preferences in a new session
    print("\n" + "=" * 60)
    print("SESSION 2: Agent recalls preferences")
    print("=" * 60 + "\n")

    agent.print_response(
        "Draft a follow-up to my last sent email that hasn't gotten a reply yet",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    # Session 3: Date-aware queries
    print("\n" + "=" * 60)
    print("SESSION 3: Date-aware email queries")
    print("=" * 60 + "\n")

    agent.print_response(
        "Show me a summary of emails I received this week",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
