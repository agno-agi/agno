"""
Multi-Component Decision Tree

Demonstrates a decision tree mixing different HITL component types:
Condition -> Loop -> Condition. Each pauses for user confirmation,
enabling complex interactive workflows.

Pattern:
1. Condition HITL: Choose analysis approach
2. Loop HITL: Confirm before starting iterative refinement
3. Condition HITL: Choose output format
"""

from agno.db.sqlite import SqliteDb
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step functions
# ============================================================
def detailed_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="Detailed analysis: all metrics computed, edge cases covered."
    )


def quick_summary(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Quick summary: key highlights identified.")


def refine_results(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(
        content=f"Refinement pass complete. Quality improved.\nPrevious: {prev[:80]}..."
    )


def formal_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(content=f"=== FORMAL REPORT ===\n{prev}")


def internal_notes(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "No analysis"
    return StepOutput(content=f"--- Internal Notes ---\n{prev}")


# ============================================================
# Build workflow: Condition -> Loop -> Condition
# ============================================================
workflow = Workflow(
    name="multi_component_tree",
    db=SqliteDb(db_file="tmp/multi_component_tree.db"),
    steps=[
        # Decision 1: Analysis depth
        Condition(
            name="analysis_depth",
            requires_confirmation=True,
            confirmation_message="Run detailed analysis? (No = quick summary)",
            on_reject=OnReject.else_branch,
            steps=[Step(name="detailed", executor=detailed_analysis)],
            else_steps=[Step(name="quick", executor=quick_summary)],
        ),
        # Decision 2: Optional refinement loop
        Loop(
            name="refinement",
            steps=[Step(name="refine", executor=refine_results)],
            max_iterations=3,
            requires_confirmation=True,
            confirmation_message="Start iterative refinement? (up to 3 passes)",
            on_reject=OnReject.skip,
        ),
        # Decision 3: Output format
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

if __name__ == "__main__":
    print("Multi-Component Decision Tree")
    print("=" * 50)

    run_output = workflow.run("Quarterly performance review")

    while run_output.is_paused:
        for req in run_output.steps_requiring_confirmation:
            print(f"\n[Decision] {req.step_name}")
            print(f"  {req.confirmation_message}")

            choice = input("\n  Your choice (yes/no): ").strip().lower()

            if choice in ("yes", "y"):
                req.confirm()
                print("  -> Confirmed")
            else:
                req.reject()
                print("  -> Rejected")

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 50)
    print(f"Status: {run_output.status}")
    print("=" * 50)
    print(run_output.content)
