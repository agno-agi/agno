"""
Let Another Slack App Talk to a Protected Bot
=============================================

Use two Slack apps in one workspace: a coordinator asks a protected reviewer for
reviews. The reviewer answers only allowed_apps, each as its service account,
and service_account=True limits the reviewer to its own account.

Prerequisites: COORDINATOR_SLACK_TOKEN, COORDINATOR_SLACK_SIGNING_SECRET, COORDINATOR_SLACK_APP_ID, REVIEWER_SLACK_TOKEN, REVIEWER_SLACK_SIGNING_SECRET, REVIEWER_SLACK_USER_ID, OPENAI_API_KEY, JWT_VERIFICATION_KEY
COORDINATOR_SLACK_APP_ID is the coordinator's app ID (A...; its app settings page); REVIEWER_SLACK_USER_ID is the reviewer bot user's Slack member ID (U...; its profile > Copy member ID)
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/authorize_apps.py
Try in Slack: As alice (create_dev_token("alice", secret=JWT_VERIFICATION_KEY)), POST /service-accounts for "coordinator-bot" and "slack-<reviewer app ID, lowercase>" with agents:slack-authorize-apps-reviewer:run, then ask the coordinator for a review; revoke either account to see it refused
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history (per app); users:read (reviewer)
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools


def required_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


# ---------------------------------------------------------------------------
# Create App-Checked Slack AgentOS
# ---------------------------------------------------------------------------

coordinator_token = required_env("COORDINATOR_SLACK_TOKEN")
coordinator_secret = required_env("COORDINATOR_SLACK_SIGNING_SECRET")
# The coordinator's Slack app ID (A...; its app settings page)
coordinator_app_id = required_env("COORDINATOR_SLACK_APP_ID")
reviewer_token = required_env("REVIEWER_SLACK_TOKEN")
reviewer_secret = required_env("REVIEWER_SLACK_SIGNING_SECRET")
# The reviewer bot user's Slack member ID (U...; its profile > Copy member ID)
reviewer_user_id = required_env("REVIEWER_SLACK_USER_ID")

db = SqliteDb(
    id="slack-authorize-apps-db",
    db_file="tmp/slack_authorize_apps.db",
)

coordinator = Agent(
    id="slack-authorize-apps-coordinator",
    name="Slack Review Coordinator",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[
        SlackTools(
            token=coordinator_token,
            enable_send_message=True,
            enable_send_message_thread=True,
            enable_list_channels=False,
            enable_get_channel_history=False,
            enable_upload_file=False,
            enable_download_file=False,
        )
    ],
    instructions=[
        "Answer normal questions directly.",
        "For a review, use send_message_thread in the current Slack thread.",
        f"Address the Reviewer with the real Slack mention <@{reviewer_user_id}>.",
        "Include a self-contained review request after the mention.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

reviewer = Agent(
    id="slack-authorize-apps-reviewer",
    name="Slack Review Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions=[
        "Answer review questions from people and from the coordinator briefly.",
        "Answer the human-readable thread without mentioning the coordinator again.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

authz = Authorization(
    verification_keys=[required_env("JWT_VERIFICATION_KEY")],
    algorithm="HS256",
)
# People in Slack get this role on their first message to the reviewer
authz.define_role(
    "slack-member",
    [
        "agents:slack-authorize-apps-reviewer:run",
        "agents:slack-authorize-apps-reviewer:read",
    ],
    default=True,
)
# The admin who creates and revokes service accounts
authz.define_role("admin", ["agent_os:admin"])
authz.seed(admin="alice")

agent_os = AgentOS(
    id="slack-authorize-apps-os",
    description="AgentOS serving a coordinator app and an app-checked reviewer app.",
    db=db,
    agents=[coordinator, reviewer],
    authorization=authz,
    user_directory=True,
    interfaces=[
        Slack(
            agent=coordinator,
            prefix="/coordinator",
            token=coordinator_token,
            signing_secret=coordinator_secret,
            respond_to_other_apps=False,
        ),
        Slack(
            agent=reviewer,
            prefix="/reviewer",
            token=reviewer_token,
            signing_secret=reviewer_secret,
            authorize_senders=True,
            respond_to_other_apps=True,
            # The coordinator runs only as this service account; any other app is refused
            allowed_apps={coordinator_app_id: "coordinator-bot"},
            # Every run is also limited to the reviewer's own account, slack-<its app ID, lowercase>
            service_account=True,
        ),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run App-Checked Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
