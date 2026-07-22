"""
Loop Confirmation HITL Example (AgentOS)

This example demonstrates pausing before a Loop starts so a human can decide
whether to run the iterative work.
"""

from agno.os import AgentOS
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from workflow_db import db


def prepare_data(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "quarterly performance"
    return StepOutput(
        content=f"Prepared data for '{topic}'.\n"
        "- Baseline metrics loaded\n"
        "- Candidate refinements identified"
    )


def refine_analysis(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No previous analysis"
    return StepOutput(
        content=f"Refinement pass complete.\n\nInput considered:\n{previous_content}\n\n"
        "- Quality score improved\n"
        "- Narrative tightened"
    )


def finalize_results(step_input: StepInput) -> StepOutput:
    previous_content = step_input.previous_step_content or "No refinement output"
    return StepOutput(content=f"Final results:\n\n{previous_content}")


workflow = Workflow(
    name="loop_confirmation_workflow",
    description="Ask for human confirmation before an iterative refinement loop.",
    db=db,
    steps=[
        Step(name="prepare_data", executor=prepare_data),
        Loop(
            name="refinement_loop",
            steps=[Step(name="refine_analysis", executor=refine_analysis)],
            max_iterations=3,
            human_review=HumanReview(
                requires_confirmation=True,
                confirmation_message="Start the refinement loop?",
            ),
        ),
        Step(name="finalize_results", executor=finalize_results),
    ],
)
workflow.id = "workflow-hitl-loop-confirmation"

agent_os = AgentOS(
    name="Workflow Loop Confirmation HITL",
    description="AgentOS workflow example for loop start confirmation.",
    workflows=[workflow],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="loop_confirmation:app", reload=True)
