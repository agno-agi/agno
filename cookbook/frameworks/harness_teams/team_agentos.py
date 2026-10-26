"""
A Team with Harness Members behind AgentOS
==========================================
Serves a team of Claude Code, Codex and an Agno agent through AgentOS. The team's page
in the AgentOS UI lists Claude Code and Codex alongside the Agno agent, and a run
streams each member's events as the leader delegates.

    .venvs/demo/bin/python cookbook/frameworks/harness_teams/team_agentos.py
    curl -N -X POST localhost:7777/teams/mixed-team/runs \\
        -F message="Add a test for the 100 dollar boundary and review it" -F stream=true

Requires OPENAI_API_KEY (leader, Codex, writer) and ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN (Claude Code). See README.md.
"""

import os
import shutil
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
# Claude edits files, so the team works on a copy of the sample project.
workspace = Path(tempfile.mkdtemp(prefix="harness-team-os-"))
shutil.copytree(
    Path(__file__).resolve().parents[1] / "sample_project",
    workspace,
    dirs_exist_ok=True,
)
db = SqliteDb(db_file=str(workspace / "team.db"))

# ---------------------------------------------------------------------------
# Create the Team
# ---------------------------------------------------------------------------
engineer = ClaudeAgent(
    id="claude-engineer",
    name="Claude Engineer",
    role="Writes and runs Python tests in the project",
    model="claude-sonnet-4-6",
    cwd=str(workspace),
    permission_mode="bypassPermissions",
    db=db,
)
reviewer = CodexAgent(
    id="codex-reviewer",
    name="Codex Reviewer",
    role="Reviews code and tests read-only; never edits files",
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    sandbox_mode="read-only",
    approval_mode="deny_all",
    reasoning_effort="low",
    db=db,
)
writer = Agent(
    id="writer",
    name="Writer",
    role="Writes a three-line summary for a product manager",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)
team = Team(
    id="mixed-team",
    name="Mixed Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[engineer, reviewer, writer],
    instructions=[
        "Delegate code changes to the Claude Engineer, reviews to the Codex Reviewer and summaries to the Writer.",
        "Only involve the members the request needs.",
    ],
    # The leader remembers earlier turns of the session, so a follow-up can refer to them.
    add_history_to_context=True,
    db=db,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(id="harness-teams", agents=[engineer, reviewer, writer], teams=[team], telemetry=False)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app, reload=False)
