"""Loop with CEL end condition: stop when agent signals completion.
================================================================

Uses last_step_content.contains() to detect a keyword in the output
that signals the loop should stop.

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
editor = Agent(
    name="Editor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "Edit and refine the text. When the text is polished and ready, "
        "include the word DONE at the end of your response."
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Content Keyword Loop",
    steps=[
        Loop(
            name="Editing Loop",
            max_iterations=5,
            end_condition='last_step_content.contains("DONE")',
            steps=[
                Step(name="Edit", agent=editor),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print('Loop with CEL end condition: last_step_content.contains("DONE")')
    print("=" * 60)
    workflow.print_response(
        input="Refine this draft: AI is changing the world in many ways.",
        stream=True,
    )
