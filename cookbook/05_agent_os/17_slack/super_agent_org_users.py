"""
Serve Super Agent to os.agno.com Members in Slack
=================================================

Serve AgentOS's built-in Super Agent in Slack to the members of the organization
that owns this AgentOS on os.agno.com, with no roles in code. Each member who
opens the AgentOS on os.agno.com is recorded in the user directory as an org
user with the role and scopes their os.agno.com token carries. In Slack they are
matched by their confirmed email and run with that access: an admin changes what
a member can do on os.agno.com (Settings, Roles), and it applies the next time
the member opens this AgentOS.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, JWT_VERIFICATION_KEY (this AgentOS's public key from os.agno.com), PostgreSQL (./cookbook/scripts/run_pgvector.sh) for the durable queue
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/super_agent_org_users.py
Try in Slack: before opening the AgentOS on os.agno.com, DM "What can you do?" and get told how to get access; open the AgentOS on os.agno.com once, then ask again and Super Agent answers as you
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, users:read, users:read.email
"""

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create the AgentOS
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="slack-org-users-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    db_schema="slack_org_users",
)
model = OpenAIResponses(id="gpt-5.6-luna")

# authorization=True verifies os.agno.com tokens with JWT_VERIFICATION_KEY, and with no roles in code each
# member's os.agno.com scopes decide. user_directory records each member who opens the AgentOS, with those scopes.
agent_os = AgentOS(
    id="slack-org-users-os",
    description="AgentOS serving Super Agent in Slack to its os.agno.com members.",
    db=db,
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    authorization=True,
    user_directory=True,
)
# The manager exists only once AgentOS is constructed.
# authorize_senders runs each member as their directory user; resolve_user_identity makes that user their
# confirmed Slack email, the same id their os.agno.com token carries.
agent_os.interfaces.append(
    Slack(team=agent_os.manager, authorize_senders=True, resolve_user_identity=True)
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
