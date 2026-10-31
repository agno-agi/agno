"""
Claude Code as a Workflow Step
==============================
A two-step workflow: Claude Code writes and runs a test in the sample project, then an
Agno agent summarises what changed for a product manager. A second run of the same
session asks Claude about the file it wrote, and it answers from its own conversation.

    .venvs/demo/bin/python cookbook/frameworks/harness_workflows/claude_step.py

Requires OPENAI_API_KEY (summary step) and ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN
(Claude Code). See README.md.
"""

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
# Claude edits files, so the workflow works on a copy of the sample project.
workspace = Path(tempfile.mkdtemp(prefix="claude-step-"))
shutil.copytree(
    Path(__file__).resolve().parents[1] / "sample_project",
    workspace,
    dirs_exist_ok=True,
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
writer = Agent(
    id="writer",
    name="Writer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Summarise the engineer's report in three short lines for a product manager.",
)
workflow = Workflow(
    id="claude-step",
    name="Claude Step",
    steps=[
        Step(name="engineer", agent=engineer),
        Step(name="summary", agent=writer),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "claude-step-" + uuid4().hex[:8]

    workflow.print_response(
        "Add test_shipping.py with a pytest test for the 100 dollar free-shipping boundary "
        "in shipping.py, run it, and report the result.",
        session_id=session_id,
        stream=True,
    )
    # Same session: Claude resumes its own conversation, so it knows which file it wrote.
    workflow.print_response(
        "Which test file did you add in the previous run, and which subtotal does it check?",
        session_id=session_id,
        stream=True,
    )
