"""
Claude Code and Codex Reviewing in Parallel
===========================================
Claude Code and Codex review the same code at the same time, each in its own
conversation, then an Agno agent merges the two reviews. Harness agents can be listed
directly in a Parallel, like Agno agents.

    .venvs/demo/bin/python cookbook/frameworks/harness_workflows/parallel_review.py

Requires OPENAI_API_KEY (Codex and the merge step) and ANTHROPIC_API_KEY or
CLAUDE_CODE_OAUTH_TOKEN (Claude Code). See README.md.
"""

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import Parallel, Step, Workflow

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(tempfile.mkdtemp(prefix="parallel-review-"))
shutil.copytree(
    Path(__file__).resolve().parents[1] / "sample_project",
    workspace,
    dirs_exist_ok=True,
)
db = SqliteDb(db_file=str(workspace / "workflow.db"))

# ---------------------------------------------------------------------------
# Create the Workflow
# ---------------------------------------------------------------------------
claude_reviewer = ClaudeAgent(
    id="claude-reviewer",
    name="Claude Reviewer",
    model="claude-sonnet-4-6",
    cwd=str(workspace),
    # Reviews only: Claude may read files but not edit them.
    allowed_tools=["Read", "Grep", "Glob"],
    db=db,
)
codex_reviewer = CodexAgent(
    id="codex-reviewer",
    name="Codex Reviewer",
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    sandbox_mode="read-only",
    approval_mode="deny_all",
    reasoning_effort="low",
    db=db,
)
editor = Agent(
    id="review-editor",
    name="Review Editor",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=(
        "You receive two code reviews. Merge them into one list of at most four findings, "
        "noting which reviewer raised each one."
    ),
)
workflow = Workflow(
    id="parallel-review",
    name="Parallel Review",
    steps=[
        Parallel(claude_reviewer, codex_reviewer, name="reviews"),
        Step(name="merge", agent=editor),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    workflow.print_response(
        "Review shipping.py for edge cases in the shipping fee. Do not edit any files. "
        "List at most three findings, each in one sentence.",
        session_id="parallel-review-" + uuid4().hex[:8],
        stream=True,
    )
