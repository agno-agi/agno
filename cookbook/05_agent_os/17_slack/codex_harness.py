"""
Codex in Slack with Native Approvals
====================================

Serve a CodexAgent in Slack. Codex asks before it runs a shell command; Slack
shows each request as an Approve / Deny card and the click answers Codex.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, CODEX_API_KEY or `codex login`
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/codex_harness.py
Try in Slack: Ask "Run python shipping.py and tell me what it prints."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

import os
from pathlib import Path

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create Codex Slack AgentOS
# ---------------------------------------------------------------------------

workspace = Path(__file__).resolve().parents[2] / "frameworks" / "sample_project"

db = SqliteDb(
    id="slack-codex-harness-db",
    db_file="tmp/slack_codex_harness.db",
)

codex_agent = CodexAgent(
    id="slack-codex-harness",
    name="Codex Shipping Reviewer",
    db=db,
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    sandbox_mode="read-only",
    approval_policy="untrusted",
    reasoning_effort="low",
)

agent_os = AgentOS(
    id="slack-codex-harness-os",
    description="AgentOS serving a Codex harness in Slack with native approvals.",
    db=db,
    agents=[codex_agent],
    interfaces=[Slack(agent=codex_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Codex Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
