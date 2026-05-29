"""
Router User Selection HITL Example (AgentOS)

This example demonstrates a Router that pauses for a human to choose which
analysis path should run.
"""

from agno.os import AgentOS
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

from workflow_db import db


def analyze_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "Q4 sales data"
    return StepOutput(
        content=f"Analysis prepared for '{topic}'.\n"
        "- 1000 records scanned\n"
        "- Data quality: good\n"
        "- Ready for a human-selected analysis path"
    )


def quick_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Quick analysis complete:\n"
        "- Summary statistics computed\n"
        "- Top trends identified\n"
        "- Confidence: 85%"
    )


def deep_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Deep analysis complete:\n"
        "- Correlation matrix generated\n"
        "- Anomalies reviewed\n"
        "- Scenario model produced\n"
        "- Confidence: 97%"
    )


def risk_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Risk analysis complete:\n"
        "- Three risk clusters identified\n"
        "- Mitigations ranked by impact\n"
        "- Follow-up owners suggested"
    )


def generate_report(step_input: StepInput) -> StepOutput:
    analysis_results = step_input.previous_step_content or "No analysis selected"
    return StepOutput(content=f"Final report:\n\n{analysis_results}")


workflow = Workflow(
    name="router_user_selection_workflow",
    description="Let a human select the workflow route from AgentOS.",
    db=db,
    steps=[
        Step(name="analyze_data", executor=analyze_data),
        Router(
            name="analysis_type_router",
            choices=[
                Step(
                    name="quick_analysis",
                    description="Fast summary with basic insights",
                    executor=quick_analysis,
                ),
                Step(
                    name="deep_analysis",
                    description="Comprehensive statistical analysis",
                    executor=deep_analysis,
                ),
                Step(
                    name="risk_analysis",
                    description="Risk-focused analysis with mitigations",
                    executor=risk_analysis,
                ),
            ],
            requires_user_input=True,
            user_input_message="Select the analysis path to run.",
            allow_multiple_selections=False,
        ),
        Step(name="generate_report", executor=generate_report),
    ],
)
workflow.id = "workflow-hitl-router-user-selection"

agent_os = AgentOS(
    name="Workflow Router Selection HITL",
    description="AgentOS workflow example for human-selected router paths.",
    workflows=[workflow],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="router_user_selection:app", reload=True)
