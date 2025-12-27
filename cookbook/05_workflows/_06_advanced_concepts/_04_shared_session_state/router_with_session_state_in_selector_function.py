"""
Example demonstrating how to access session_state in Router selectors.

This example shows:
1. Using session_state in a Router selector function
2. Making routing decisions based on session state data
3. Accessing user preferences and history from session_state
4. Dynamically selecting different agents based on user context
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow


def route_based_on_user_preference(step_input: StepInput, session_state: dict) -> Step:
    """
    Router selector that chooses an agent based on user preferences in session_state.

    Args:
        step_input: The input for this step (contains user query)
        session_state: The shared session state dictionary

    Returns:
        Step: The step to execute based on user preference
    """
    print("\n=== Routing Decision ===")
    print(f"User ID: {session_state.get('current_user_id')}")
    print(f"Session ID: {session_state.get('current_session_id')}")

    # Get user preference from session state
    user_preference = session_state.get("agent_preference", "general")
    interaction_count = session_state.get("interaction_count", 0)

    print(f"User Preference: {user_preference}")
    print(f"Interaction Count: {interaction_count}")

    # Update interaction count
    session_state["interaction_count"] = interaction_count + 1

    # Route based on preference
    if user_preference == "technical":
        print("→ Routing to Technical Expert")
        return technical_step
    elif user_preference == "friendly":
        print("→ Routing to Friendly Assistant")
        return friendly_step
    else:
        # For first interaction, route to onboarding
        if interaction_count == 0:
            print("→ Routing to Onboarding (first interaction)")
            return onboarding_step
        else:
            print("→ Routing to General Assistant")
            return general_step


def set_user_preference(step_input: StepInput, session_state: dict) -> StepOutput:
    """Custom function that sets user preference based on onboarding."""
    print("\n=== Setting User Preference ===")

    # In a real scenario, this would analyze the user's response
    # For demo purposes, we'll set it based on interaction count
    interaction_count = session_state.get("interaction_count", 0)

    if interaction_count % 3 == 1:
        session_state["agent_preference"] = "technical"
        preference = "technical"
    elif interaction_count % 3 == 2:
        session_state["agent_preference"] = "friendly"
        preference = "friendly"
    else:
        session_state["agent_preference"] = "general"
        preference = "general"

    print(f"Set preference to: {preference}")
    return StepOutput(content=f"Preference set to: {preference}")


# Create specialized agents
onboarding_agent = Agent(
    name="Onboarding Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "Welcome new users and ask about their preferences. "
        "Determine if they prefer technical or friendly assistance."
    ),
    markdown=True,
)

technical_agent = Agent(
    name="Technical Expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "You are a technical expert. Provide detailed, technical answers with code examples and best practices."
    ),
    markdown=True,
)

friendly_agent = Agent(
    name="Friendly Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "You are a friendly, casual assistant. Use simple language, emojis, and make the conversation fun."
    ),
    markdown=True,
)

general_agent = Agent(
    name="General Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "You are a balanced assistant. Provide helpful answers that are neither too technical nor too casual."
    ),
    markdown=True,
)

# Create steps for routing
onboarding_step = Step(
    name="Onboard User",
    description="Onboard new user and set preferences",
    agent=onboarding_agent,
)

technical_step = Step(
    name="Technical Response",
    description="Provide technical assistance",
    agent=technical_agent,
)

friendly_step = Step(
    name="Friendly Response",
    description="Provide friendly assistance",
    agent=friendly_agent,
)

general_step = Step(
    name="General Response",
    description="Provide general assistance",
    agent=general_agent,
)

# Create workflow with router
workflow = Workflow(
    name="Adaptive Assistant Workflow",
    steps=[
        # Router that selects agent based on session state
        Router(
            name="Route to Appropriate Agent",
            description="Route to the appropriate agent based on user preferences",
            selector=route_based_on_user_preference,
            choices=[
                onboarding_step,
                technical_step,
                friendly_step,
                general_step,
            ],
        ),
        # After first interaction, update preferences
        Step(
            name="Update Preferences",
            description="Update user preferences based on interaction",
            executor=set_user_preference,
        ),
    ],
    session_state={
        "agent_preference": "general",
        "interaction_count": 0,
    },
)


def run_example():
    """Run the example workflow multiple times to see dynamic routing."""

    queries = [
        "Hello! I'm new here.",
        "How do I implement a binary search tree in Python?",
        "What's the best pizza topping?",
        "Explain quantum computing",
    ]

    for i, query in enumerate(queries, 1):
        print("\n" + "=" * 80)
        print(f"Interaction {i}: {query}")
        print("=" * 80)

        workflow.print_response(
            input=query,
            session_id="user-456",
            user_id="user-456",
            stream=True,
        )


if __name__ == "__main__":
    run_example()
