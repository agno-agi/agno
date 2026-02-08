"""Condition with CEL expression: branching on additional_data.
============================================================

Uses additional_data.priority to route high-priority requests
to a specialized agent.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Step, Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
high_priority_agent = Agent(
    name="High Priority Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle high-priority tasks. Be thorough and detailed.",
    markdown=True,
)

low_priority_agent = Agent(
    name="Low Priority Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle standard tasks. Be helpful and concise.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Priority Routing",
    steps=[
        Condition(
            name="Priority Gate",
            evaluator="additional_data.priority > 5",
            steps=[
                Step(name="High Priority", agent=high_priority_agent),
            ],
            else_steps=[
                Step(name="Low Priority", agent=low_priority_agent),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- High priority (8) ---")
    workflow.print_response(
        input="Review this critical security report.",
        additional_data={"priority": 8},
    )
    print()

    print("--- Low priority (2) ---")
    workflow.print_response(
        input="Update the FAQ page.",
        additional_data={"priority": 2},
    )
