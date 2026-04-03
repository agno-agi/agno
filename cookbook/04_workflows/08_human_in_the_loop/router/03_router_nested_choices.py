"""
Router with Nested Choices HITL Example

This example demonstrates how to use HITL with nested step lists in Router choices.
When choices contain nested lists like [step_a, [step_b, step_c]], the nested list
becomes a Steps container that executes ALL steps in sequence when selected.

Use cases:
- Pre-defined pipelines that user can choose from
- "Packages" of processing steps (e.g., "Basic", "Standard", "Premium")
- Workflow templates where user picks a complete flow

Flow:
1. Receive input (automatic)
2. User selects a processing package (single step OR a sequence of steps)
3. Execute the selected package (if nested, all steps run in sequence)
4. Generate output (automatic)

Key concept:
- choices=[step_a, [step_b, step_c], step_d]
  - "step_a" -> executes just step_a
  - "steps_group_1" -> executes step_b THEN step_c (chained)
  - "step_d" -> executes just step_d
"""

from agno.db.sqlite import SqliteDb
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step 1: Receive input (automatic)
# ============================================================
def receive_input(step_input: StepInput) -> StepOutput:
    """Receive and validate input."""
    user_query = step_input.input or "document"
    return StepOutput(
        content=f"Input received: '{user_query}'\n"
        "Ready for processing.\n\n"
        "Please select a processing package."
    )


# ============================================================
# Individual processing steps
# ============================================================
def quick_scan(step_input: StepInput) -> StepOutput:
    """Quick scan - fast but basic."""
    prev = step_input.previous_step_content or ""
    return StepOutput(
        content=f"{prev}\n\n[QUICK SCAN]\n"
        "- Surface-level analysis\n"
        "- Key points extracted\n"
        "- Processing time: 30 seconds"
    )


def deep_analysis(step_input: StepInput) -> StepOutput:
    """Deep analysis - thorough examination."""
    prev = step_input.previous_step_content or ""
    return StepOutput(
        content=f"{prev}\n\n[DEEP ANALYSIS]\n"
        "- Comprehensive examination\n"
        "- Pattern detection applied\n"
        "- Processing time: 5 minutes"
    )


def quality_check(step_input: StepInput) -> StepOutput:
    """Quality check - verify results."""
    prev = step_input.previous_step_content or ""
    return StepOutput(
        content=f"{prev}\n\n[QUALITY CHECK]\n"
        "- Results validated\n"
        "- Accuracy verified: 98%\n"
        "- Processing time: 1 minute"
    )


def format_output(step_input: StepInput) -> StepOutput:
    """Format output - prepare final results."""
    prev = step_input.previous_step_content or ""
    return StepOutput(
        content=f"{prev}\n\n[FORMAT OUTPUT]\n"
        "- Results formatted\n"
        "- Report generated\n"
        "- Processing time: 30 seconds"
    )


def archive_results(step_input: StepInput) -> StepOutput:
    """Archive results - store for future reference."""
    prev = step_input.previous_step_content or ""
    return StepOutput(
        content=f"{prev}\n\n[ARCHIVE]\n"
        "- Results archived\n"
        "- Backup created\n"
        "- Processing time: 15 seconds"
    )


# ============================================================
# Final step (automatic)
# ============================================================
def finalize(step_input: StepInput) -> StepOutput:
    """Finalize and return results."""
    results = step_input.previous_step_content or "No processing performed"
    return StepOutput(
        content=f"=== FINAL RESULTS ===\n\n{results}\n\n=== PROCESSING COMPLETE ==="
    )


# Define individual steps
quick_scan_step = Step(
    name="quick_scan", description="Fast surface-level scan (30s)", executor=quick_scan
)

# Define step sequences as Steps containers with descriptive names
standard_package = Steps(
    name="standard_package",
    description="Standard processing: Deep Analysis + Quality Check (6 min)",
    steps=[
        Step(name="deep_analysis", executor=deep_analysis),
        Step(name="quality_check", executor=quality_check),
    ],
)

premium_package = Steps(
    name="premium_package",
    description="Premium processing: Deep Analysis + Quality Check + Format + Archive (8 min)",
    steps=[
        Step(name="deep_analysis", executor=deep_analysis),
        Step(name="quality_check", executor=quality_check),
        Step(name="format_output", executor=format_output),
        Step(name="archive_results", executor=archive_results),
    ],
)

# Create workflow with Router HITL
# User can select:
# - "quick_scan" -> runs just quick_scan
# - "standard_package" -> runs deep_analysis THEN quality_check
# - "premium_package" -> runs deep_analysis THEN quality_check THEN format_output THEN archive_results
workflow = Workflow(
    name="package_selection_workflow",
    db=SqliteDb(db_file="tmp/workflow_router_nested.db"),
    steps=[
        Step(name="receive_input", executor=receive_input),
        Router(
            name="package_selector",
            choices=[
                quick_scan_step,  # Single step
                standard_package,  # Steps container (2 steps)
                premium_package,  # Steps container (4 steps)
            ],
            requires_user_input=True,
            user_input_message="Select a processing package:",
            allow_multiple_selections=False,  # Pick ONE package
        ),
        Step(name="finalize", executor=finalize),
    ],
)

# Alternative: Using nested lists directly (auto-converted to Steps containers)
# Note: Auto-generated names like "steps_group_0" are less descriptive
workflow_with_nested_lists = Workflow(
    name="nested_list_workflow",
    db=SqliteDb(db_file="tmp/workflow_router_nested_alt.db"),
    steps=[
        Step(name="receive_input", executor=receive_input),
        Router(
            name="package_selector",
            choices=[
                Step(
                    name="quick_scan",
                    description="Fast scan (30s)",
                    executor=quick_scan,
                ),
                # Nested list -> becomes "steps_group_1" Steps container
                [
                    Step(name="deep_analysis", executor=deep_analysis),
                    Step(name="quality_check", executor=quality_check),
                ],
                # Nested list -> becomes "steps_group_2" Steps container
                [
                    Step(name="deep_analysis", executor=deep_analysis),
                    Step(name="quality_check", executor=quality_check),
                    Step(name="format_output", executor=format_output),
                    Step(name="archive_results", executor=archive_results),
                ],
            ],
            requires_user_input=True,
            user_input_message="Select a processing option:",
        ),
        Step(name="finalize", executor=finalize),
    ],
)

if __name__ == "__main__":
    print("=" * 60)
    print("Router with Nested Choices (Pre-defined Packages)")
    print("=" * 60)
    print("\nThis example shows how to offer 'packages' of steps.")
    print("Each package can be a single step or a sequence of steps.\n")

    run_output = workflow.run("quarterly report")

    # Handle HITL pauses
    while run_output.is_paused:
        # Handle Router requirements (user selection)
        for requirement in run_output.steps_requiring_route:
            print(f"\n[DECISION POINT] {requirement.step_name}")
            print(f"[HITL] {requirement.user_input_message}")

            # Show available packages
            print("\nAvailable packages:")
            for i, choice in enumerate(requirement.available_choices or [], 1):
                # Get description if available from the router's choices
                print(f"  {i}. {choice}")

            print("\nPackage details:")
            print("  - quick_scan: Fast surface-level scan (30s)")
            print("  - standard_package: Deep Analysis + Quality Check (6 min)")
            print("  - premium_package: Full pipeline with archiving (8 min)")

            selection = input("\nEnter your choice: ").strip()
            if selection:
                requirement.select(selection)
                print(f"\n[HITL] Selected package: {selection}")

        for requirement in run_output.steps_requiring_confirmation:
            print(
                f"\n[HITL] {requirement.step_name}: {requirement.confirmation_message}"
            )
            if input("Continue? (yes/no): ").strip().lower() in ("yes", "y"):
                requirement.confirm()
            else:
                requirement.reject()

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print(f"Status: {run_output.status}")
    print("=" * 60)
    print(run_output.content)
