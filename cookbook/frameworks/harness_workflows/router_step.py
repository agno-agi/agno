"""
Routing Between Claude Code and Codex
=====================================
A Router sends a change request to Claude Code, which may edit the project, and a
question to Codex, which reads it read-only. The same workflow handles both kinds of
request.

    .venvs/demo/bin/python cookbook/frameworks/harness_workflows/router_step.py

Requires OPENAI_API_KEY (Codex) and ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN
(Claude Code). See README.md.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import List
from uuid import uuid4

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.workflow import Router, Step, StepInput, Workflow

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(tempfile.mkdtemp(prefix="router-step-"))
shutil.copytree(
    Path(__file__).resolve().parents[1] / "sample_project",
    workspace,
    dirs_exist_ok=True,
)
db = SqliteDb(db_file=str(workspace / "workflow.db"))

# ---------------------------------------------------------------------------
# Create the Workflow
# ---------------------------------------------------------------------------
change = Step(
    name="change",
    agent=ClaudeAgent(
        id="claude-engineer",
        name="Claude Engineer",
        model="claude-sonnet-4-6",
        cwd=str(workspace),
        permission_mode="bypassPermissions",
        db=db,
    ),
)
question = Step(
    name="question",
    agent=CodexAgent(
        id="codex-reader",
        name="Codex Reader",
        model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
        cwd=str(workspace),
        sandbox_mode="read-only",
        approval_mode="deny_all",
        reasoning_effort="low",
        db=db,
    ),
)


def route(step_input: StepInput) -> List[Step]:
    """Requests that change the project go to Claude Code; everything else goes to Codex."""
    text = str(step_input.input).lower()
    return [change] if text.startswith(("add", "change", "fix")) else [question]


workflow = Workflow(
    id="router-step",
    name="Router Step",
    steps=[Router(name="route", selector=route, choices=[change, question])],
    db=db,
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "router-step-" + uuid4().hex[:8]
    workflow.print_response(
        "What does shipping_fee return for a subtotal of 100? Answer in one sentence.",
        session_id=session_id,
        stream=True,
    )
    workflow.print_response(
        "Add a docstring example to shipping_fee showing the fee for a subtotal of 40. "
        "Reply with the new docstring only.",
        session_id=session_id,
        stream=True,
    )
