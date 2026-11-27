"""
Check Every Slack Sender's Roles
================================

Run each Slack sender as their user in the AgentOS user directory with
authorize_senders=True. A new sender gets a user on their first message, with
the default role; an admin can grant other roles or disable them in /users.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, JWT_VERIFICATION_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/authorize_senders.py
Try in Slack: Ask "Which plans do we offer?", then, with a token for "alice" (create_dev_token("alice", secret=JWT_VERIFICATION_KEY)), check GET /users for your new slack:{workspace}:{member} user; disable it with PATCH /users/{id} and ask again
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, users:read
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.os.interfaces.slack import Slack


def required_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


# ---------------------------------------------------------------------------
# Create Sender-Checked Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-authorize-senders-db",
    db_file="tmp/slack_authorize_senders.db",
)

support_agent = Agent(
    id="slack-authorize-senders-agent",
    name="Slack Plans Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions=[
        "Answer questions about the Starter, Team and Enterprise plans briefly."
    ],
    markdown=True,
)

authz = Authorization(
    verification_keys=[required_env("JWT_VERIFICATION_KEY")],
    algorithm="HS256",
)
# Every new Slack sender gets this role on their first message
authz.define_role(
    "slack-member",
    [
        "agents:slack-authorize-senders-agent:run",
        "agents:slack-authorize-senders-agent:read",
    ],
    default=True,
)
# The admin who manages /users and /authz
authz.define_role("admin", ["agent_os:admin"])
authz.seed(admin="alice")

agent_os = AgentOS(
    id="slack-authorize-senders-os",
    description="AgentOS running each Slack sender as their own directory user.",
    db=db,
    agents=[support_agent],
    authorization=authz,
    user_directory=True,
    interfaces=[Slack(agent=support_agent, authorize_senders=True)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Sender-Checked Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
