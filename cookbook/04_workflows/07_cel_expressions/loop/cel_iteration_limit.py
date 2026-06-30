"""Loop with CEL end condition: stop after N iterations.
=====================================================

Uses current_iteration to stop after a specific number
of iterations, independent of max_iterations.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a short paragraph expanding on the topic. Build on previous content.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Iteration Limit Loop",
    steps=[
        Loop(
            name="Writing Loop",
            max_iterations=10,
            # Stop after 2 iterations even though max is 10
            end_condition="current_iteration >= 2",
            steps=[
                Step(name="Write", agent=writer),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Loop with CEL end condition: current_iteration >= 2 (max_iterations=10)")
    print("=" * 60)
    workflow.print_response(
        input="Write about the history of the internet",
        stream=True,
    )
