"""
Claude Code in Slack with Native Approvals
==========================================

Serve a ClaudeAgent in Slack. Each tool call Claude Code asks about becomes an
Approve / Deny card, and the click answers the Claude Code process that waits.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/claude_harness.py
Try in Slack: Ask "Run python shipping.py and tell me what it prints."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create Claude Slack AgentOS
# ---------------------------------------------------------------------------

workspace = Path(__file__).resolve().parents[2] / "frameworks" / "sample_project"

db = SqliteDb(
    id="slack-claude-harness-db",
    db_file="tmp/slack_claude_harness.db",
)

claude_agent = ClaudeAgent(
    id="slack-claude-harness",
    name="Claude Shipping Reviewer",
    db=db,
    model="claude-sonnet-5-5",
    cwd=str(workspace),
    allowed_tools=["Read"],
    permission_mode="default",
    tools=["Read", "Bash"],
    setting_sources=[],
    strict_mcp_config=True,
)

agent_os = AgentOS(
    id="slack-claude-harness-os",
    description="AgentOS serving a Claude Code harness in Slack with native approvals.",
    db=db,
    agents=[claude_agent],
    interfaces=[Slack(agent=claude_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Claude Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
