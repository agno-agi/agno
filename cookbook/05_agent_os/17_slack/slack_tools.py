"""
Search Slack and Work with Files
================================

Combine channel history, thread expansion, workspace search, and file
download/upload in one focused SlackTools Agent.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/slack_tools.py
Try in Slack: Share a file, then ask for related discussions and an uploaded summary
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, channels:read, channels:history, groups:read, groups:history, files:read, files:write, search:read.public, search:read.files, search:read.users
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools

# ---------------------------------------------------------------------------
# Create Slack Tools AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-tools-db",
    db_file="tmp/slack_tools.db",
)

workspace_tools = SlackTools(
    output_directory="tmp/slack_downloads",
    enable_send_message=False,
    enable_send_message_thread=False,
    enable_list_channels=True,
    enable_get_channel_history=True,
    enable_upload_file=True,
    enable_download_file=True,
    enable_search_workspace=True,
    enable_get_thread=True,
    enable_list_users=False,
    enable_get_user_info=False,
    enable_get_channel_info=True,
)

workspace_analyst = Agent(
    id="slack-workspace-analyst",
    name="Slack Workspace Analyst",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "Use Slack as the source of truth for workspace questions.",
        "Use search_workspace for topic searches; its action token comes from the Slack event.",
        "Use get_channel_history for a known channel and get_thread to expand important replies.",
        "Download shared files when analysis needs their contents.",
        "Upload a result file only when the user explicitly asks for one.",
        "Summarize decisions, owners, action items, and unresolved questions.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-tools-os",
    description="AgentOS serving a Slack-native workspace and file analyst.",
    agents=[workspace_analyst],
    interfaces=[Slack(agent=workspace_analyst)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Slack Tools AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
