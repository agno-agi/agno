"""
Claude Code in a Loop Until the Tests Pass
==========================================
A Loop runs a Claude Code step until it reports that every test passes, up to three
times. Claude often fixes the failing test and re-runs pytest in one turn; when it needs
another iteration, that iteration resumes the same Claude conversation, so Claude builds
on what it already did instead of starting over.

    .venvs/demo/bin/python cookbook/frameworks/harness_workflows/loop_until_green.py

Requires ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN (Claude Code). See README.md.
"""

import shutil
import tempfile
from pathlib import Path
from typing import List
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.workflow import Loop, Step, StepOutput, Workflow

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(tempfile.mkdtemp(prefix="loop-until-green-"))
shutil.copytree(
    Path(__file__).resolve().parents[1] / "sample_project",
    workspace,
    dirs_exist_ok=True,
)
# A failing test for Claude to fix: the free-shipping threshold is 100, not 50.
(workspace / "test_threshold.py").write_text(
    "from shipping import shipping_fee\n\n\n"
    "def test_free_shipping_starts_at_the_threshold():\n"
    "    assert shipping_fee(50) == 0\n"
)
db = SqliteDb(db_file=str(workspace / "workflow.db"))

# ---------------------------------------------------------------------------
# Create the Workflow
# ---------------------------------------------------------------------------
engineer = ClaudeAgent(
    id="claude-engineer",
    name="Claude Engineer",
    model="claude-sonnet-4-6",
    cwd=str(workspace),
    permission_mode="bypassPermissions",
    db=db,
)


def tests_pass(outputs: List[StepOutput]) -> bool:
    """End the loop once the engineer reports a green test run."""
    return any("ALL TESTS PASS" in str(output.content) for output in outputs)


workflow = Workflow(
    id="loop-until-green",
    name="Loop Until Green",
    steps=[
        Loop(
            name="fix-tests",
            steps=[Step(name="engineer", agent=engineer)],
            end_condition=tests_pass,
            max_iterations=3,
        )
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    workflow.print_response(
        "Run pytest. If a test is wrong about the shipping policy in shipping.py, fix the test, "
        "not shipping.py, and run pytest again. End your reply with ALL TESTS PASS only when "
        "pytest passes.",
        session_id="loop-until-green-" + uuid4().hex[:8],
        stream=True,
    )
