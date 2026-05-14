"""
Decision Tree HITL Example (AgentOS)

This example demonstrates multiple sequential human decisions in one workflow.
Each Condition pauses in AgentOS and the selected branch shapes the final output.
"""

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

db = SqliteDb(db_file="tmp/agentos_workflow_decision_tree.db")


def gather_requirements(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "Q4 sales performance"
    return StepOutput(
        content=f"Requirements gathered for '{topic}'.\n"
        "Ready for analysis depth and output format decisions."
    )


def detailed_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Detailed analysis complete:\n"
        "- Full statistical review\n"
        "- Edge cases examined\n"
        "- Confidence level: 95%"
    )


def quick_summary(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Quick summary complete:\n"
        "- Key metrics computed\n"
        "- Top highlights identified"
    )


def formal_report(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No analysis"
    return StepOutput(
        content=f"Formal stakeholder report:\n\n{previous_content}\n\n"
        "Formatted for presentation."
    )


def internal_notes(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No analysis"
    return StepOutput(
        content=f"Internal team notes:\n\n{previous_content}\n\n"
        "Saved as team reference material."
    )


workflow = Workflow(
    name="decision_tree_workflow",
    description="Guide a workflow through sequential human decisions in AgentOS.",
    db=db,
    steps=[
        Step(name="gather_requirements", executor=gather_requirements),
        Condition(
            name="analysis_depth",
            requires_confirmation=True,
            confirmation_message="Perform detailed analysis? Reject for quick summary.",
            on_reject=OnReject.else_branch,
            steps=[Step(name="detailed_analysis", executor=detailed_analysis)],
            else_steps=[Step(name="quick_summary", executor=quick_summary)],
        ),
        Condition(
            name="output_format",
            requires_confirmation=True,
            confirmation_message="Generate a formal report? Reject for internal notes.",
            on_reject=OnReject.else_branch,
            steps=[Step(name="formal_report", executor=formal_report)],
            else_steps=[Step(name="internal_notes", executor=internal_notes)],
        ),
    ],
)
workflow.id = "workflow-hitl-decision-tree"

agent_os = AgentOS(
    name="Workflow Decision Tree HITL",
    description="AgentOS workflow example for sequential human decisions.",
    workflows=[workflow],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="decision_tree:app", reload=True)
