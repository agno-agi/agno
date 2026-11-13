"""
Claude Code, Codex and an Agno Agent in One Team
================================================
Three members with different runtimes behind one leader: Claude Code writes a test,
Codex reviews it read-only, and a native Agno agent writes the summary. The leader
decides the order. Each harness keeps its own conversation for this session, so the
two never mix, and every member run lands in the team's run as usual.

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
from agno.team import Team

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(tempfile.mkdtemp(prefix="mixed-team-"))
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
        "First have the Claude Engineer write and run the test, then the Codex Reviewer review it, "
        "then the Writer summarise both. Keep your own final answer to the Writer's summary.",
    ],
    # The leader remembers earlier turns of the session, so a follow-up can refer to them.
    add_history_to_context=True,
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "Add test_shipping.py covering the 100 dollar boundary and a negative subtotal for shipping.py.",
        session_id="mixed-review",
        stream=True,
        show_member_responses=True,
    )
