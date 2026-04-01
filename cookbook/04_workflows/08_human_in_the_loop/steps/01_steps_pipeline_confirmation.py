"""
Steps Pipeline with User Confirmation HITL Example

This example demonstrates how to use HITL with a Steps component,
allowing the user to confirm before executing an entire pipeline of steps.

When `requires_confirmation=True` on a Steps component:
- User confirms -> Execute all steps in the pipeline
- User rejects -> Skip the entire pipeline

This is useful for:
- Optional processing pipelines
- Expensive/time-consuming step groups
- User-controlled workflow sections
"""

from agno.db.sqlite import SqliteDb
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step functions
# ============================================================
def collect_data(step_input: StepInput) -> StepOutput:
    """Collect initial data."""
    return StepOutput(
        content="Data collection complete:\n"
        "- 1000 records gathered\n"
        "- Ready for optional advanced processing"
    )


# Advanced processing pipeline steps
def validate_data(step_input: StepInput) -> StepOutput:
    """Validate the data."""
    return StepOutput(
        content="Validation complete:\n"
        "- Schema validation passed\n"
        "- Data integrity verified"
    )


def transform_data(step_input: StepInput) -> StepOutput:
    """Transform the data."""
    return StepOutput(
        content="Transformation complete:\n- Data normalized\n- Outliers handled"
    )


def enrich_data(step_input: StepInput) -> StepOutput:
    """Enrich the data with additional information."""
    return StepOutput(
        content="Enrichment complete:\n"
        "- External data merged\n"
        "- Derived fields computed"
    )


def generate_report(step_input: StepInput) -> StepOutput:
    """Generate final report."""
    previous_content = step_input.previous_step_content or "Basic data"
    return StepOutput(
        content=f"=== FINAL REPORT ===\n\n{previous_content}\n\n"
        "Report generated successfully."
    )


# Define the steps
collect_step = Step(name="collect_data", executor=collect_data)

# Steps pipeline with HITL confirmation
# User must confirm to run this entire pipeline
advanced_processing = Steps(
    name="advanced_processing_pipeline",
    steps=[
        Step(name="validate_data", executor=validate_data),
        Step(name="transform_data", executor=transform_data),
        Step(name="enrich_data", executor=enrich_data),
    ],
    requires_confirmation=True,
    confirmation_message="Run advanced processing pipeline? (This includes validation, transformation, and enrichment)",
)

report_step = Step(name="generate_report", executor=generate_report)

# Create workflow with database for HITL persistence
workflow = Workflow(
    name="steps_pipeline_confirmation_demo",
    steps=[collect_step, advanced_processing, report_step],
    db=SqliteDb(db_file="tmp/steps_hitl.db"),
)

if __name__ == "__main__":
    print("=" * 60)
    print("Steps Pipeline with User Confirmation HITL Example")
    print("=" * 60)

    run_output = workflow.run("Process quarterly data")

    # Handle HITL pauses
    while run_output.is_paused:
        # Handle Step requirements (confirmation for pipeline)
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[DECISION POINT] {requirement.step_name}")
            print(f"[HITL] {requirement.confirmation_message}")

            user_choice = input("\nRun this pipeline? (yes/no): ").strip().lower()
            if user_choice in ("yes", "y"):
                requirement.confirm()
                print("[HITL] Confirmed - executing pipeline")
            else:
                requirement.reject()
                print("[HITL] Rejected - skipping pipeline")

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print(f"Status: {run_output.status}")
    print("=" * 60)
    print(run_output.content)
