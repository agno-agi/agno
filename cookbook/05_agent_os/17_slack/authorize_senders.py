"""
Slack Senders as Users
======================

Run each Slack message as its sender's own user in the AgentOS user directory.

- The sender's confirmed Slack email is their user id. It is the same id as their
  sign-in on the web, so one person is one user in both places.
- The user is created on their first message, with the role a new user gets
  ("member" here).
- Their role and their disabled switch are read on every message.
- Super Agent needs platform access. A member gets a private reply that says to
  ask their admin. Move them to "platform" and their next message runs.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/authorize_senders.py
Try in Slack: send the bot "What can you do?". As a new member you get the private
reply. Run the request printed at startup with your email, then send it again.
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, users:read, users:read.email
"""

import os

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.os.auth import create_dev_token
from agno.os.authz import PLATFORM, READ, RUN, Authorization, Role, UserDirectory
from agno.os.interfaces.slack import Slack

PORT = 7777
# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/slack_senders.db")
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Roles: a member uses the agents, a platform user also uses Super Agent
# ---------------------------------------------------------------------------

member = Role("member", scopes=READ + RUN)
platform = Role("platform", scopes=READ + RUN + PLATFORM)

# ---------------------------------------------------------------------------
# Create AgentOS with Super Agent on Slack
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="slack-senders-os",
    description="AgentOS whose Slack senders are users in its user directory.",
    db=db,
    manager=OSManager(model=model, access_docs=False),
    authorization=Authorization(
        roles=[member, platform], verification_keys=[JWT_SECRET], algorithm="HS256"
    ),
    # A new user, from a token or from Slack, starts as a member
    user_directory=UserDirectory(default_role=member),
)
# The manager exists only once AgentOS is constructed.
agent_os.interfaces.append(
    Slack(
        team=agent_os.manager,
        # Each message runs as its sender's own user in the user directory
        authorize_senders=True,
        # The sender's confirmed Slack email is that user's id
        resolve_user_identity=True,
    )
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    admin_token = create_dev_token(
        "admin@example.com", secret=JWT_SECRET, scopes=["agent_os:admin"]
    )
    print("To give a sender platform access, with the email on their Slack profile:")
    print(
        f"  curl -X POST localhost:{PORT}/authz/subjects/<email>/roles "
        f'-H "Authorization: Bearer {admin_token}" '
        '-H "Content-Type: application/json" -d \'{"role": "platform"}\''
    )
    agent_os.serve(app=app, port=PORT)
