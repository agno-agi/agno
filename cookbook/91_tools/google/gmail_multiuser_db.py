"""
Gmail Multi-User DB Token Storage
==================================
Demonstrates per-user token isolation with DB storage. Each user_id gets
its own token row. User A's credentials never leak to User B.

Flow:
1. User 1 authenticates via browser OAuth -> token stored under user_id="user-1"
2. User 2 authenticates via browser OAuth -> token stored under user_id="user-2"
3. Verify both tokens exist and are isolated in the DB

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser twice (once per user) for OAuth consent
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Setup — shared DB, separate user_ids
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/gmail_multiuser.db")

agent = Agent(
    name="Gmail Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[GmailTools(store_token_in_db=True, include_tools=["get_latest_emails"])],
    db=db,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # User 1 — browser opens for OAuth, token stored under "user-1"
    print("--- User 1 ---")
    agent.print_response(
        "Show my latest email subject",
        stream=True,
        user_id="user-1",
    )

    # User 2 — browser opens again for separate OAuth, token stored under "user-2"
    print("\n--- User 2 ---")
    agent.print_response(
        "Show my latest email subject",
        stream=True,
        user_id="user-2",
    )

    # Verify isolation
    print("\n--- DB Verification ---")
    for uid in ["user-1", "user-2"]:
        row = db.get_auth_token("google", uid, "google")
        print(f"  {uid}: {'token found' if row else 'NO TOKEN'}")
