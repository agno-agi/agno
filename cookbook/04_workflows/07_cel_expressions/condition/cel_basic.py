"""Condition with CEL expression: route based on input content.
============================================================

Uses input.contains() to check whether the request is urgent,
branching to different agents via if/else steps.

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
urgent_handler = Agent(
    name="Urgent Handler",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle urgent requests with high priority. Be concise and action-oriented.",
    markdown=True,
)

normal_handler = Agent(
    name="Normal Handler",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle normal requests thoroughly and thoughtfully.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Input Routing",
    steps=[
        Condition(
            name="Urgent Check",
            evaluator='input.contains("urgent")',
            steps=[
                Step(name="Handle Urgent", agent=urgent_handler),
            ],
            else_steps=[
                Step(name="Handle Normal", agent=normal_handler),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Urgent request ---")
    workflow.print_response(
        input="This is an urgent request - please help immediately!"
    )
    print()

    print("--- Normal request ---")
    workflow.print_response(input="I have a general question about your services.")
