"""
Router with Confirmation HITL Example

This example demonstrates the confirmation mode for Router components,
which is different from the user selection mode.

When `requires_confirmation=True` on a Router (with a selector):
- The selector determines which steps to run
- User is asked to confirm before executing those steps
- User confirms -> Execute the selected steps
- User rejects -> Skip the router entirely

This is useful for:
- Confirming automated routing decisions
- Human oversight of programmatic selections
- Safety checks before executing routed steps

Note: This is different from `requires_user_input=True` which lets the user
choose which steps to execute. Here, the selector chooses, but user confirms.
"""

from agno.db.sqlite import SqliteDb
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ============================================================
# Step functions
# ============================================================
def analyze_request(step_input: StepInput) -> StepOutput:
    """Analyze the request to determine routing."""
    user_query = step_input.input or "general request"
    # Determine category based on content
    if "urgent" in user_query.lower():
        category = "urgent"
    elif "billing" in user_query.lower():
        category = "billing"
    else:
        category = "general"

    return StepOutput(
        content=f"Request analyzed:\n"
        f"- Query: {user_query}\n"
        f"- Detected category: {category}\n"
        "- Ready for routing"
    )


def handle_urgent(step_input: StepInput) -> StepOutput:
    """Handle urgent requests."""
    return StepOutput(
        content="Urgent Request Handling:\n"
        "- Priority escalation initiated\n"
        "- Immediate response generated\n"
        "- Notification sent to on-call team"
    )


def handle_billing(step_input: StepInput) -> StepOutput:
    """Handle billing requests."""
    return StepOutput(
        content="Billing Request Handling:\n"
        "- Account details retrieved\n"
        "- Billing history analyzed\n"
        "- Response prepared"
    )


def handle_general(step_input: StepInput) -> StepOutput:
    """Handle general requests."""
    return StepOutput(
        content="General Request Handling:\n"
        "- Standard processing applied\n"
        "- Response generated"
    )


def finalize_response(step_input: StepInput) -> StepOutput:
    """Finalize the response."""
    previous_content = step_input.previous_step_content or "No handling"
    return StepOutput(
        content=f"=== FINAL RESPONSE ===\n\n{previous_content}\n\nRequest processed successfully."
    )


# Selector function that determines routing based on previous step content
def route_by_category(step_input: StepInput) -> str:
    """Route based on detected category in previous step."""
    content = step_input.previous_step_content or ""
    if "urgent" in content.lower():
        return "handle_urgent"
    elif "billing" in content.lower():
        return "handle_billing"
    else:
        return "handle_general"


# Define the steps
analyze_step = Step(name="analyze_request", executor=analyze_request)

# Router with confirmation - selector chooses, user confirms
request_router = Router(
    name="request_router",
    choices=[
        Step(
            name="handle_urgent",
            description="Handle urgent requests",
            executor=handle_urgent,
        ),
        Step(
            name="handle_billing",
            description="Handle billing requests",
            executor=handle_billing,
        ),
        Step(
            name="handle_general",
            description="Handle general requests",
            executor=handle_general,
        ),
    ],
    selector=route_by_category,
    requires_confirmation=True,
    confirmation_message="The system has selected a handler. Proceed with the routed action?",
)

finalize_step = Step(name="finalize_response", executor=finalize_response)

# Create workflow with database for HITL persistence
workflow = Workflow(
    name="router_confirmation_demo",
    steps=[analyze_step, request_router, finalize_step],
    db=SqliteDb(db_file="tmp/router_hitl.db"),
)

if __name__ == "__main__":
    print("=" * 60)
    print("Router with Confirmation HITL Example")
    print("=" * 60)
    print("The selector will choose the route, but you must confirm.")
    print()

    # Test with an urgent request
    run_output = workflow.run("URGENT: System is down!")

    # Handle HITL pauses
    while run_output.is_paused:
        # Handle Step requirements (confirmation for router)
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[ROUTING DECISION] {requirement.step_name}")
            print(f"[HITL] {requirement.confirmation_message}")

            user_choice = input("\nProceed with routing? (yes/no): ").strip().lower()
            if user_choice in ("yes", "y"):
                requirement.confirm()
                print("[HITL] Confirmed - executing routed steps")
            else:
                requirement.reject()
                print("[HITL] Rejected - skipping router")

        run_output = workflow.continue_run(run_output)

    print("\n" + "=" * 60)
    print(f"Status: {run_output.status}")
    print("=" * 60)
    print(run_output.content)
