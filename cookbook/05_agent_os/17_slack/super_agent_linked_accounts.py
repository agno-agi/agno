"""
Super Agent in Slack with Agno Accounts
=======================================

Serve Super Agent in Slack, where each member acts as their own os.agno.com
account. A member's first message gets a private "Link your Agno account"
button. They sign in on os.agno.com and confirm, and from then on their
messages run as that account, with the permissions it has on this AgentOS.

The platform checks every message: the account must still be an active member
of the organization that owns this AgentOS. Removing someone on os.agno.com
stops their Slack access on their next message. No Slack role is defined here.

Setup on os.agno.com, for the AgentOS registered with this OS id:
1. Settings > Security: turn on JWT and copy the public key into JWT_VERIFICATION_KEY.
2. Settings > Security > OS service token: generate one into AGNO_OS_SERVICE_TOKEN.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, JWT_VERIFICATION_KEY,
AGNO_OS_SERVICE_TOKEN, PostgreSQL (./cookbook/scripts/run_pgvector.sh)
Optional: AGNO_PLATFORM_API_URL (defaults to https://os-api.agno.com/api/v1)
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/super_agent_linked_accounts.py
Try in Slack: DM the bot, press "Link your Agno account", confirm, then send "What can you do?" again
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, mpim:history, channels:history, groups:history, users:read, users:read.email
"""

import os

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack

PORT = 7777
# The id the AgentOS is registered with on os.agno.com; its user tokens are issued for it
OS_ID = os.getenv("AGENT_OS_ID", "slack-linked-accounts-os")

db = PostgresDb(
    id="slack-linked-accounts-db",
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="slack_linked_accounts",
)
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create the AgentOS
# ---------------------------------------------------------------------------

# authorization=True verifies os.agno.com tokens with JWT_VERIFICATION_KEY and checks
# each caller's scopes, so a linked member gets exactly the access they have on os.agno.com.
# AGNO_OS_SERVICE_TOKEN turns on account linking for Super Agent in Slack.
agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS serving Super Agent in Slack to linked Agno accounts.",
    db=db,
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    authorization=True,
)
# The manager exists only once AgentOS is constructed.
agent_os.interfaces.append(Slack(team=agent_os.manager))
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=PORT, reload=False)
