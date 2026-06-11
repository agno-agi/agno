"""
Condition User Decision HITL Example (AgentOS)

This example demonstrates a human-controlled Condition. Confirming runs the
primary branch; rejecting runs the else branch.
"""

from agno.os import AgentOS
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

from workflow_db import db


def analyze_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "Q4 sales data"
    return StepOutput(
        content=f"Initial analysis complete for '{topic}'.\n"
        "- Detailed review is available\n"
        "- Quick summary is also available"
    )


def detailed_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Detailed analysis results:\n"
        "- Full statistical review completed\n"
        "- Edge cases examined\n"
        "- Processing time estimate: 10 minutes"
    )


def quick_summary(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Quick summary results:\n"
        "- Key metrics computed\n"
        "- Top highlights identified\n"
        "- Processing time estimate: 1 minute"
    )


def generate_report(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No analysis output"
    return StepOutput(content=f"Generated report:\n\n{previous_content}")


workflow = Workflow(
    name="condition_user_decision_workflow",
    description="Use AgentOS confirmation to choose a Condition branch.",
    db=db,
    steps=[
        Step(name="analyze_data", executor=analyze_data),
        Condition(
            name="analysis_depth_decision",
            requires_confirmation=True,
            confirmation_message="Run detailed analysis? Reject to use quick summary.",
            on_reject=OnReject.else_branch,
            steps=[Step(name="detailed_analysis", executor=detailed_analysis)],
            else_steps=[Step(name="quick_summary", executor=quick_summary)],
        ),
        Step(name="generate_report", executor=generate_report),
    ],
)
workflow.id = "workflow-hitl-condition-user-decision"

agent_os = AgentOS(
    name="Workflow Condition Decision HITL",
    description="AgentOS workflow example for human-controlled conditions.",
    workflows=[workflow],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="condition_user_decision:app", reload=True)
