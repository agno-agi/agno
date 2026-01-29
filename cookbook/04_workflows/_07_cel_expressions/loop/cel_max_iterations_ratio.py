"""Loop with CEL end condition: stop at a fraction of max_iterations.

Uses iteration and max_iterations together to stop
at the halfway point of the configured max.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

drafter = Agent(
    name="Drafter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Draft or refine content based on the topic. Improve with each iteration.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Max Iterations Ratio Loop",
    steps=[
        Loop(
            name="Drafting Loop",
            max_iterations=6,
            # Stop at halfway (iteration 3 of 6)
            end_condition="iteration >= max_iterations / 2",
            steps=[
                Step(name="Draft", agent=drafter),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: iteration >= max_iterations / 2")
    print("max_iterations=6, so loop stops after 3 iterations")
    print("=" * 60)
    workflow.print_response(
        input="Write a product launch announcement",
        stream=True,
    )
