"""
Codex as a Team Member
======================
An Agno team whose reviewer is Codex. The leader delegates a read-only code review to
Codex, which reads the project with its own tools, and then asks a follow-up on the
same session; Codex continues the same thread instead of starting over.

Requires OPENAI_API_KEY for the leader and for Codex. See README.md.
"""

import os
from pathlib import Path

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
storage = Path(__file__).resolve().parent / "tmp"
storage.mkdir(exist_ok=True)
db = SqliteDb(db_file=str(storage / "codex_member.db"))

# ---------------------------------------------------------------------------
# Create the Team
# ---------------------------------------------------------------------------
reviewer = CodexAgent(
    id="codex-reviewer",
    name="Codex Reviewer",
    role="Reviews Python code for bugs and missing edge cases; never edits files",
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    sandbox_mode="read-only",
    approval_mode="deny_all",
    reasoning_effort="low",
    db=db,
)
team = Team(
    id="review-team",
    name="Review Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[reviewer],
    instructions=[
        "Delegate every code question to the Codex Reviewer and relay its answer briefly."
    ],
    # The leader remembers earlier turns of the session, so a follow-up can refer to them.
    add_history_to_context=True,
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "shipping-code-review"

    team.print_response(
        "Review shipping.py. List at most three concrete issues.",
        session_id=session_id,
        stream=True,
        show_member_responses=True,
    )
    # Same session: the reviewer continues its Codex thread instead of starting over.
    team.print_response(
        "Ask the reviewer: of the points it just made about shipping.py, which matters most for the "
        "100 dollar boundary, and why?",
        session_id=session_id,
        stream=True,
        show_member_responses=True,
    )
