"""
Slack Multi-User Group Threads
==============================

Slack bot supporting multi-user conversations in threads. Multiple users
can participate in the same thread, sharing conversation history while
keeping their memories isolated.

Key Features:
- `multi_user_threads=True`: Enables shared sessions for group threads
- All users in a thread share the same conversation history
- Each user's memories remain isolated (per user_id)
- HITL (Human-in-the-Loop) works across users in the thread

SECURITY NOTES:
---------------
1. Slack verifies user identity via signed requests - user_id is trustworthy
2. Use `resolve_user_identity=True` to get email addresses instead of Slack IDs
3. Use `hitl_owner_only=True` to restrict tool approvals to the user who triggered them

Prerequisites:
--------------
1. Create a Slack app at https://api.slack.com/apps
2. Set environment variables:
   - SLACK_BOT_TOKEN: Bot User OAuth Token (xoxb-...)
   - SLACK_SIGNING_SECRET: Signing Secret from App Credentials

Run:
----
1. Start ngrok: ngrok http 8001
2. Configure Slack Event URL: https://<ngrok-url>/slack/events
3. Run: .venvs/demo/bin/python cookbook/integrations/slack/multiuser_group_threads.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack

db = SqliteDb(db_file="tmp/slack_multiuser.db")

agent = Agent(
    name="TeamAssistant",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You are a helpful team assistant in a Slack workspace.",
        "Multiple team members may be talking to you in the same thread.",
        "Be helpful, concise, and address users by name when relevant.",
    ],
    db=db,
    add_history_to_context=True,
    num_history_runs=20,
    enable_user_memories=True,
    markdown=True,
)

slack = Slack(
    agent=agent,
    prefix="/slack",
    # Enable multi-user shared sessions for group threads
    multi_user_threads=True,
    # Resolve Slack user IDs to email addresses
    resolve_user_identity=True,
    # Optional: Restrict HITL approvals to the user who triggered the tool
    # hitl_owner_only=True,
)

agent_os = AgentOS(
    name="SlackMultiUserDemo",
    agents=[agent],
    interfaces=[slack],
)

app = agent_os.get_app()

print("=" * 60)
print("SLACK MULTI-USER GROUP THREADS DEMO")
print("=" * 60)
print()
print("How it works:")
print("  1. First message in a thread creates the session")
print("  2. All subsequent users share the same session")
print("  3. Everyone sees the full conversation history")
print("  4. Each user's memories remain isolated")
print()
print("Configuration:")
print(f"  multi_user_threads:    {slack.multi_user_threads}")
print(f"  resolve_user_identity: {slack.resolve_user_identity}")
print()
print("Endpoints:")
print("  POST /slack/events     - Slack Event Subscriptions")
print("  POST /slack/actions    - Slack Interactive Components")
print()
print("Starting server on port 8001...")
print("=" * 60)

agent_os.serve(app="multiuser_group_threads:app", port=8001, reload=True)
