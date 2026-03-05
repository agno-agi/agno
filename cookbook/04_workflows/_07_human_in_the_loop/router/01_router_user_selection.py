"""
Router with User Selection HITL Example

This example demonstrates how to create a user-driven decision tree using
a Router where the user selects which path to take at runtime.

The Router with HITL pattern is powerful for:
- Interactive wizards
- User-driven workflows
- Decision trees with human judgment
- Dynamic routing based on user preferences

Flow:
1. Analyze data (automatic step)
2. User chooses analysis type via Router HITL
3. Execute the chosen analysis path
4. Generate report (automatic step)
"""

from agno.db.sqlite import SqliteDb
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step 1: Analyze data (automatic)
# ============================================================
def analyze_data(step_input: StepInput) -> StepOutput:
    """Analyze the data and provide options."""
    user_query = step_input.input or "data"
    return StepOutput(
        content=f"Analysis complete for '{user_query}':\n"
        "- Found 1000 records\n"
        "- Data quality: Good\n"
        "- Ready for processing\n\n"
        "Please choose how you'd like to proceed."
    )


# ============================================================
# Router Choice Steps
# ============================================================
def quick_analysis(step_input: StepInput) -> StepOutput:
    """Perform quick analysis."""
    return StepOutput(
        content="Quick Analysis Results:\n"
        "- Summary statistics computed\n"
        "- Basic trends identified\n"
        "- Processing time: 2 minutes\n"
        "- Confidence: 85%"
    )


def deep_analysis(step_input: StepInput) -> StepOutput:
    """Perform deep analysis."""
    return StepOutput(
        content="Deep Analysis Results:\n"
        "- Comprehensive statistical analysis\n"
        "- Pattern recognition applied\n"
        "- Anomaly detection completed\n"
        "- Correlation matrix generated\n"
        "- Processing time: 10 minutes\n"
        "- Confidence: 97%"
    )


def custom_analysis(step_input: StepInput) -> StepOutput:
    """Perform custom analysis based on user preferences."""
    user_input = (
        step_input.additional_data.get("user_input", {})
        if step_input.additional_data
        else {}
    )
    params = user_input.get("custom_params", "default parameters")

    return StepOutput(
        content=f"Custom Analysis Results:\n"
        f"- Custom parameters applied: {params}\n"
        "- Tailored analysis completed\n"
        "- Processing time: varies\n"
        "- Confidence: based on parameters"
    )


# ============================================================
# Step 4: Generate report (automatic)
# ============================================================
def generate_report(step_input: StepInput) -> StepOutput:
    """Generate final report."""
    analysis_results = step_input.previous_step_content or "No results"
    return StepOutput(
        content=f"=== FINAL REPORT ===\n\n{analysis_results}\n\n"
        "Report generated successfully.\n"
        "Thank you for using the analysis workflow!"
    )


# Define the analysis step
analyze_step = Step(name="analyze_data", executor=analyze_data)

# Define the Router with HITL - user selects which analysis to perform
analysis_router = Router(
    name="analysis_type_router",
    choices=[
        Step(
            name="quick_analysis",
            description="Fast analysis with basic insights (2 min)",
            executor=quick_analysis,
        ),
        Step(
            name="deep_analysis",
            description="Comprehensive analysis with full details (10 min)",
            executor=deep_analysis,
        ),
        Step(
            name="custom_analysis",
            description="Custom analysis with your parameters",
            executor=custom_analysis,
        ),
    ],
    requires_user_input=True,
    user_input_message="Select the type of analysis to perform:",
    allow_multiple_selections=False,  # Only one analysis type at a time
)

# Define the report step
report_step = Step(name="generate_report", executor=generate_report)

# Create workflow
workflow = Workflow(
    name="user_driven_analysis",
    db=SqliteDb(db_file="tmp/workflow_router_hitl.db"),
    steps=[analyze_step, analysis_router, report_step],
)

if __name__ == "__main__":
    print("=" * 60)
    print("User-Driven Analysis Workflow with Router HITL")
    print("=" * 60)

    run_output = workflow.run("Q4 sales data")

    # Handle HITL pauses
    while run_output.is_paused:
        # Handle Router requirements (user selection)
        # with requires_route_selection=True
        for requirement in run_output.steps_requiring_route:
            print(f"\n[DECISION POINT] Router: {requirement.step_name}")
            print(f"[HITL] {requirement.user_input_message}")

            # Show available choices
            print("\nAvailable options:")
            for choice in requirement.available_choices or []:
                print(f"  - {choice}")

            # Get user selection
            selection = input("\nEnter your choice: ").strip()
            if selection:
                requirement.select(selection)
                print(f"\n[HITL] Selected: {selection}")

        # Handle Step requirements (confirmation or user input)
        for requirement in run_output.steps_requiring_user_input:
            print(f"\n[HITL] Step: {requirement.step_name}")
            print(f"[HITL] {requirement.user_input_message}")

            if requirement.user_input_schema:
                user_values = {}
                for field in requirement.user_input_schema:
                    required_marker = "*" if field.required else ""
                    if field.description:
                        print(f"  ({field.description})")
                    value = input(f"{field.name}{required_marker}: ").strip()
                    if value:
                        user_values[field.name] = value
                requirement.set_user_input(**user_values)

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
