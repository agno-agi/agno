"""
Claude Code as a Team Member
============================
An Agno team whose engineer is Claude Code. The leader, a normal Agno model, decides
what to delegate; Claude Code does the work in its own workspace with its own tools;
a native Agno agent writes the summary. Two turns on one session show that Claude
remembers the first turn when the leader delegates to it again.

The member keeps its Claude conversation in a session of its own, derived from the
team's session id, so the team's session stays the team's and the member's runs are
stored in it like any other member's.

Requires OPENAI_API_KEY for the leader and the writer, and ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN for Claude Code. See README.md.
"""

import shutil
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
# Claude edits files, so it works on a copy of the sample project.
workspace = Path(tempfile.mkdtemp(prefix="harness-team-"))
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
    role="Writes and runs Python code in the project",
    model="claude-sonnet-4-6",
    cwd=str(workspace),
    permission_mode="bypassPermissions",
    db=db,
)
writer = Agent(
    id="writer",
    name="Writer",
    role="Turns technical results into a two-line summary for a product manager",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)
team = Team(
    id="shipping-team",
    name="Shipping Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[engineer, writer],
    instructions=[
        "Delegate coding work to the Claude Engineer and summaries to the Writer.",
        "Keep your final answer short.",
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "shipping-review"

    team.print_response(
        "Add test_shipping.py with a pytest test for the exact 100 dollar boundary in shipping.py, "
        "run it, then have the result summarised.",
        session_id=session_id,
        stream=True,
        show_member_responses=True,
    )
    # Same session: the engineer answers from its own Claude conversation of the first turn.
    team.print_response(
        "Ask the engineer which test file it created last time and what it asserts.",
        session_id=session_id,
        stream=True,
        show_member_responses=True,
    )
    print(
        "Files in the workspace:", sorted(path.name for path in workspace.glob("*.py"))
    )
