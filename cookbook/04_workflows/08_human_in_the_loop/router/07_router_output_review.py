"""
Router Post-Execution Review -- Approve / Re-route / Cancel

Demonstrates reviewing a Router's output using the HITL config class,
and optionally picking a different branch:

    START -> Router (selector picks branch) -> [PAUSE for review]
                                               +- approve  -> next step -> END
                                               +- re-route -> pick different branch -> [PAUSE again]
                                               +- cancel   -> END

The Router runs its selector, executes the chosen branch, then pauses for
human review. If rejected, the human picks a different branch from the
available choices. The new branch runs and pauses for review again.

Run:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/router/07_router_output_review.py
"""

from agno.db.sqlite import SqliteDb
from agno.workflow import OnReject
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ---------------------------------------------------------------------------
# Analysis steps (Router choices)
# ---------------------------------------------------------------------------
def quick_analysis(step_input: StepInput) -> StepOutput:
    """Fast but shallow analysis."""
    return StepOutput(
        content="Quick Analysis:\n"
        "- Summary statistics computed\n"
        "- Basic trends identified\n"
        "- Confidence: 85%"
    )


def deep_analysis(step_input: StepInput) -> StepOutput:
    """Thorough but slow analysis."""
    return StepOutput(
        content="Deep Analysis:\n"
        "- Comprehensive statistical analysis\n"
        "- Pattern recognition applied\n"
        "- Anomaly detection completed\n"
        "- Confidence: 97%"
    )


def custom_analysis(step_input: StepInput) -> StepOutput:
    """Custom analysis with user parameters."""
    return StepOutput(
        content="Custom Analysis:\n"
        "- Tailored parameters applied\n"
        "- Domain-specific insights generated\n"
        "- Confidence: 92%"
    )


# ---------------------------------------------------------------------------
# Report step (runs after Router is approved)
# ---------------------------------------------------------------------------
def generate_report(step_input: StepInput) -> StepOutput:
    """Generate a report from the approved analysis."""
    analysis = step_input.previous_step_content or "No analysis"
    return StepOutput(content=f"=== FINAL REPORT ===\n\n{analysis}\n\nReport complete.")


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="router_review_workflow",
    db=SqliteDb(db_file="tmp/router_review.db"),
    steps=[
        Router(
            name="analysis_router",
            # Selector auto-picks quick analysis
            selector=lambda si: [Step(name="quick", executor=quick_analysis)],
            choices=[
                Step(
                    name="quick",
                    description="Fast analysis (2 min)",
                    executor=quick_analysis,
                ),
                Step(
                    name="deep",
                    description="Thorough analysis (10 min)",
                    executor=deep_analysis,
                ),
                Step(
                    name="custom",
                    description="Custom analysis",
                    executor=custom_analysis,
                ),
            ],
            # Post-execution review via HITL config: human reviews output, can re-route
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review the analysis result. Approve, or pick a different analysis type?",
                on_reject=OnReject.retry,
                max_retries=5,
            ),
        ),
        Step(name="report", executor=generate_report),
    ],
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Router Post-Execution Review Workflow")
    print("=" * 60)

    run_output = workflow.run("Analyze Q4 sales data")

    while run_output.is_paused:
        # Handle output review (approve / re-route)
        for req in run_output.steps_requiring_output_review:
            print(f"\nRouter '{req.step_name}' produced:")
            # Show the inner step outputs
            if req.step_output and req.step_output.steps:
                for inner in req.step_output.steps:
                    print(f"  {inner.content}")
            elif req.step_output:
                print(f"  {req.step_output.content}")

            print(f"\n{req.output_review_message}")
            print(f"Available routes: {req.available_choices}")

            choice = input("\nApprove this result? (yes/no/cancel): ").strip().lower()
            if choice in ("yes", "y"):
                req.confirm()
            elif choice in ("cancel", "c"):
                req.reject()
                req.on_reject = "cancel"
            else:
                req.reject()

        # Handle route selection (after rejection)
        for req in run_output.steps_requiring_route:
            print(f"\nPick a different route for '{req.step_name}':")
            for name in req.available_choices or []:
                print(f"  - {name}")
            selection = input("Your choice: ").strip()
            req.select(selection)

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print(f"Status: {run_output.status}")
    print("=" * 60)
    if run_output.content:
        print(run_output.content)
