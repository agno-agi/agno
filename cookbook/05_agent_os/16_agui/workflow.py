"""
Serve a Workflow over AG-UI
===========================

Mount an AgentOS Workflow on AG-UI. Each step becomes an AG-UI step span, an
agent step streams its own text, and a plain Python step streams nothing so the
interface emits that step's output as its own assistant message.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/workflow.py
Try: POST "Plan a small internal status page" to http://localhost:7777/workflow/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-workflow-db",
    db_file="tmp/agui_workflow.db",
)

planner = Agent(
    id="agui-workflow-planner",
    name="Planner",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Break the request into three concrete milestones. One short line each.",
)

reviewer = Agent(
    id="agui-workflow-reviewer",
    name="Reviewer",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Name the biggest risk in the supplied plan and how to reduce it.",
)


def summarize_run(step_input: StepInput) -> StepOutput:
    """A step with no model. It runs last because it reports on the steps before it.

    A failed step still leaves an output behind, so the names are split on success
    and both lists are reported. Naming only the completed steps would make a run
    whose earlier steps all failed read exactly like a run with no earlier steps.
    """
    previous_outputs = step_input.previous_step_outputs or {}
    succeeded = [name for name, output in previous_outputs.items() if output.success]
    failed = [name for name, output in previous_outputs.items() if not output.success]
    completed = ", ".join(succeeded) if succeeded else "none"
    summary = f"Run summary. Steps completed before this one: {completed}."
    if failed:
        summary += f" Steps that failed: {', '.join(failed)}."
    return StepOutput(content=summary)


launch_workflow = Workflow(
    id="agui-launch-workflow",
    name="AG-UI Launch Workflow",
    db=db,
    steps=[
        Step(name="Plan", agent=planner),
        Step(name="Review", agent=reviewer),
        Step(name="Summary", executor=summarize_run),
    ],
)

agent_os = AgentOS(
    id="agui-workflow-os",
    description="A multi-step Workflow served through AG-UI.",
    workflows=[launch_workflow],
    interfaces=[AGUI(workflow=launch_workflow, prefix="/workflow")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Workflow Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
