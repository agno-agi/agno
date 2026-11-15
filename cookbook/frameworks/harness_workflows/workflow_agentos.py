"""
A Harness Workflow behind AgentOS
=================================
Serves a workflow in which Claude Code writes a test, Codex reviews it and an Agno agent
summarises both. The workflow's page in the AgentOS UI shows each step's agent, and the
Claude and Codex agents are also served on their own: running them directly saves their
runs in their own sessions, separate from the workflow's.

    .venvs/demo/bin/python cookbook/frameworks/harness_workflows/workflow_agentos.py
    curl -N -X POST localhost:7777/workflows/build-and-review/runs \\
        -F message="Add a test for the 100 dollar boundary" -F stream=true

Requires OPENAI_API_KEY (Codex and the summary step) and ANTHROPIC_API_KEY or
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
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(tempfile.mkdtemp(prefix="harness-workflow-os-"))
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
    description="Writes and runs Python tests in the project",
    model="claude-sonnet-4-6",
    cwd=str(workspace),
    permission_mode="bypassPermissions",
    db=db,
)
reviewer = CodexAgent(
    id="codex-reviewer",
    name="Codex Reviewer",
    description="Reviews code and tests read-only; never edits files",
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
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Summarise the change and the review in three short lines for a product manager.",
)
workflow = Workflow(
    id="build-and-review",
    name="Build and Review",
    steps=[
        Step(name="build", agent=engineer),
        Step(name="review", agent=reviewer),
        Step(name="summary", agent=writer),
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="harness-workflows",
    agents=[engineer, reviewer],
    workflows=[workflow],
    telemetry=False,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app, reload=False)
