"""Condition with CEL expression: branching on session_state.
==========================================================

Uses session_state.retry_count to implement retry logic.
Runs the workflow multiple times to show the counter incrementing
and eventually hitting the max retries branch.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import (
    CEL_AVAILABLE,
    Condition,
    Step,
    StepInput,
    StepOutput,
    Workflow,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)


# ---------------------------------------------------------------------------
# Define Helpers
# ---------------------------------------------------------------------------
def increment_retry_count(step_input: StepInput, session_state: dict) -> StepOutput:
    """Increment retry count in session state."""
    current_count = session_state.get("retry_count", 0)
    session_state["retry_count"] = current_count + 1
    return StepOutput(
        content=f"Retry count incremented to {session_state['retry_count']}",
        success=True,
    )


def reset_retry_count(step_input: StepInput, session_state: dict) -> StepOutput:
    """Reset retry count in session state."""
    session_state["retry_count"] = 0
    return StepOutput(content="Retry count reset to 0", success=True)


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
retry_agent = Agent(
    name="Retry Handler",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are handling a retry attempt. Acknowledge this is a retry and try a different approach.",
    markdown=True,
)

max_retries_agent = Agent(
    name="Max Retries Handler",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Maximum retries reached. Provide a helpful fallback response and suggest alternatives.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Retry Logic",
    steps=[
        Step(name="Increment Retry", executor=increment_retry_count),
        Condition(
            name="Retry Check",
            evaluator="session_state.retry_count <= 3",
            steps=[
                Step(name="Attempt Retry", agent=retry_agent),
            ],
            else_steps=[
                Step(name="Max Retries Reached", agent=max_retries_agent),
                Step(name="Reset Counter", executor=reset_retry_count),
            ],
        ),
    ],
    session_state={"retry_count": 0},
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for attempt in range(1, 6):
        print(f"--- Attempt {attempt} ---")
        workflow.print_response(
            input=f"Process request (attempt {attempt})",
            stream=True,
        )
        print()
