"""
Model Hook
=============================

Demonstrates a function-based model hook on a team.
"""

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.models.openai import OpenAIResponses
from agno.run.messages import RunMessages
from agno.team import Team


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def log_message_context(run_messages: RunMessages, team: Team) -> None:
    """Model hook: log a summary of the message context before model call."""
    message_count = len(run_messages.messages)
    has_system = run_messages.system_message is not None
    has_user = run_messages.user_message is not None

    print(f"   [model_hook] Team: {team.name}")
    print(f"   [model_hook] Messages in context: {message_count}")
    print(f"   [model_hook] Has system message: {has_system}")
    print(f"   [model_hook] Has user message: {has_user}")


def block_forbidden_words(run_messages: RunMessages) -> None:
    """Model hook: block requests containing forbidden words in the full context."""
    forbidden = ["classified", "top secret", "confidential"]

    # Check the user message content
    if run_messages.user_message and run_messages.user_message.content:
        content = str(run_messages.user_message.content).lower()
        for word in forbidden:
            if word in content:
                raise InputCheckError(
                    f"Forbidden word detected in context: {word}",
                    check_trigger="FORBIDDEN_WORD",
                )


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
planner = Agent(
    name="Planner",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Expert in planning and organizing tasks",
)

executor = Agent(
    name="Executor",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Expert in executing and delivering results",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Model Hook Demo Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[planner, executor],
    model_hooks=[log_message_context, block_forbidden_words],
    description="A team demonstrating function-based model hooks.",
    instructions="Collaborate to provide well-planned and actionable responses.",
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
def main() -> None:
    print("Team Model Hook Examples")
    print("=" * 50)

    print("\n[TEST 1] Normal request - model hook logs context")
    print("-" * 30)
    try:
        team.print_response(
            input="What are three steps to launch a new product?",
        )
        print("[OK] Request processed after model hook inspection")
    except InputCheckError as e:
        print(f"[ERROR] Unexpected error: {e}")

    print("\n[TEST 2] Forbidden word in input - blocked by model hook")
    print("-" * 30)
    try:
        team.print_response(
            input="Please share the top secret launch plans for Q4.",
        )
        print("[WARNING] This should have been blocked!")
    except InputCheckError as e:
        print(f"[BLOCKED] Model hook blocked request: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 3] Another clean request - model hook logs context")
    print("-" * 30)
    try:
        team.print_response(
            input="Summarize the key principles of agile development.",
        )
        print("[OK] Request processed after model hook inspection")
    except InputCheckError as e:
        print(f"[ERROR] Unexpected error: {e}")


if __name__ == "__main__":
    main()
