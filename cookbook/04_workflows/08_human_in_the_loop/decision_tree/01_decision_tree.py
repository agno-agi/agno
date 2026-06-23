"""
Decision Tree with Sequential HITL Conditions

Demonstrates building a multi-step interactive decision tree using
sequential top-level Condition steps. Each Condition pauses for user
confirmation, enabling workflows where the user guides execution
through multiple branching decisions.

Pattern: Step -> Condition HITL -> Condition HITL -> Step

Each Condition uses:
- requires_confirmation=True to pause for user input
- on_reject=OnReject.else_branch to run the alternative branch on rejection
"""

from agno.db.sqlite import SqliteDb
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step functions for each branch
# ============================================================
def gather_requirements(step_input: StepInput) -> StepOutput:
    topic = step_input.input or "general"
    return StepOutput(
        content=f"Requirements gathered for '{topic}'.\n"
        "Ready for analysis approach selection."
    )


def detailed_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Detailed analysis complete:\n"
        "- Full statistical review\n"
        "- All edge cases examined\n"
        "- Confidence level: 95%"
    )


def quick_summary(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Quick summary complete:\n"
        "- Key metrics computed\n"
        "- Top highlights identified"
    )


def formal_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(
        content=f"=== FORMAL REPORT ===\n\n{prev}\n\n"
        "Report formatted for stakeholder presentation."
    )


def internal_notes(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(
        content=f"--- Internal Notes ---\n\n{prev}\n\nSaved as team reference document."
    )


# ============================================================
# Build the decision tree workflow
# ============================================================
workflow = Workflow(
    name="decision_tree",
    db=SqliteDb(db_file="tmp/decision_tree.db"),
    steps=[
        # Step 1: Gather requirements (no HITL)
        Step(name="gather", executor=gather_requirements),
        # Decision 1: Analysis depth
        Condition(
            name="analysis_depth",
            requires_confirmation=True,
            confirmation_message="Perform detailed analysis? (No = quick summary)",
            on_reject=OnReject.else_branch,
            steps=[Step(name="detailed", executor=detailed_analysis)],
            else_steps=[Step(name="quick", executor=quick_summary)],
        ),
        # Decision 2: Output format
        Condition(
            name="output_format",
            requires_confirmation=True,
            confirmation_message="Generate formal report? (No = internal notes)",
            on_reject=OnReject.else_branch,
            steps=[Step(name="formal", executor=formal_report)],
            else_steps=[Step(name="notes", executor=internal_notes)],
        ),
    ],
)

# ============================================================
# Run with interactive HITL
# ============================================================
if __name__ == "__main__":
    print("Decision Tree Workflow")
    print("=" * 50)

    run_output = workflow.run("Q4 sales performance")

    # Handle each decision point
    while run_output.is_paused:
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[Decision] {requirement.step_name}")
            print(f"  {requirement.confirmation_message}")

            choice = input("\n  Your choice (yes/no): ").strip().lower()

            if choice in ("yes", "y"):
                requirement.confirm()
                print("  -> Confirmed")
            else:
                requirement.reject()
                print("  -> Rejected (taking alternative path)")

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 50)
    print(f"Status: {run_output.status}")
    print("=" * 50)
    print(run_output.content)
