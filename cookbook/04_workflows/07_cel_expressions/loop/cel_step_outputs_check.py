"""Loop with CEL end condition: check a named step's output.
=========================================================

Uses step_outputs map to access a specific step by name and
check its content before deciding to stop the loop.

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
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the given topic.",
    markdown=True,
)

reviewer = Agent(
    name="Reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "Review the research. If the research is thorough and complete, "
        "include APPROVED in your response."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Step Outputs Check Loop",
    steps=[
        Loop(
            name="Research Loop",
            max_iterations=5,
            # Stop when the Reviewer step approves the research
            end_condition='step_outputs.Review.contains("APPROVED")',
            steps=[
                Step(name="Research", agent=researcher),
                Step(name="Review", agent=reviewer),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print('Loop with CEL end condition: step_outputs.Review.contains("APPROVED")')
    print("=" * 60)
    workflow.print_response(
        input="Research renewable energy trends",
        stream=True,
    )
