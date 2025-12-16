"""
Example demonstrating how to access session_state in Condition evaluators.

This example shows:
1. Using session_state in a Condition evaluator function
2. Reading and modifying session_state based on condition logic
3. Accessing user_id and session_id from session_state
4. Making conditional decisions based on session state data
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.condition import Condition
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow


def check_user_has_context(step_input: StepInput, session_state: dict) -> bool:
    """
    Condition evaluator that checks if user has been greeted before.

    Args:
        step_input: The input for this step (contains workflow context)
        session_state: The shared session state dictionary

    Returns:
        bool: True if user has context, False otherwise
    """
    print("\n=== Evaluating Condition ===")
    print(f"User ID: {session_state.get('current_user_id')}")
    print(f"Session ID: {session_state.get('current_session_id')}")
    print(f"Has been greeted: {session_state.get('has_been_greeted', False)}")

    # Check if user has been greeted before
    return session_state.get("has_been_greeted", False)


def mark_user_as_greeted(step_input: StepInput, session_state: dict) -> StepOutput:
    """Custom function that marks user as greeted in session state."""
    print("\n=== Marking User as Greeted ===")
    session_state["has_been_greeted"] = True
    session_state["greeting_count"] = session_state.get("greeting_count", 0) + 1

    return StepOutput(
        content=f"User has been greeted. Total greetings: {session_state['greeting_count']}"
    )


# Create agents
greeter_agent = Agent(
    name="Greeter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Greet the user warmly and introduce yourself.",
    markdown=True,
)

contextual_agent = Agent(
    name="Contextual Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Continue the conversation with context. You already know the user.",
    markdown=True,
)

# Create workflow with condition
workflow = Workflow(
    name="Conditional Greeting Workflow",
    steps=[
        # First, check if user has been greeted before
        Condition(
            name="Check If New User",
            description="Check if this is a new user who needs greeting",
            # Condition returns True if user has context, so we negate it
            evaluator=lambda step_input, session_state: not check_user_has_context(
                step_input, session_state
            ),
            steps=[
                # Only execute these steps for new users
                Step(
                    name="Greet User",
                    description="Greet the new user",
                    agent=greeter_agent,
                ),
                Step(
                    name="Mark as Greeted",
                    description="Mark user as greeted in session",
                    executor=mark_user_as_greeted,
                ),
            ],
        ),
        # This step always executes
        Step(
            name="Handle Query",
            description="Handle the user's query with or without greeting",
            agent=contextual_agent,
        ),
    ],
    session_state={
        "has_been_greeted": False,
        "greeting_count": 0,
    },
)


def run_example():
    """Run the example workflow multiple times to see conditional behavior."""

    print("=" * 80)
    print("First Run - New User (Condition will be True, greeting will happen)")
    print("=" * 80)

    workflow.print_response(
        input="Hi, can you help me with something?",
        session_id="user-123",
        user_id="user-123",
        stream=True,
    )

    print("\n" + "=" * 80)
    print("Second Run - Same Session (Skips greeting)")
    print("=" * 80)

    workflow.print_response(
        input="Tell me a joke",
        session_id="user-123",
        user_id="user-123",
        stream=True,
    )


if __name__ == "__main__":
    run_example()
