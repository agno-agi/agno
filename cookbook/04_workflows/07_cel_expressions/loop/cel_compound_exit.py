"""Loop with CEL end condition: compound exit condition.
=====================================================

Combines all_success and current_iteration to stop when both
conditions are met: all steps succeeded AND enough iterations ran.

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
    instructions="Research the given topic and provide detailed findings.",
    markdown=True,
)

reviewer = Agent(
    name="Reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Review the research for completeness and accuracy.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Compound Exit Loop",
    steps=[
        Loop(
            name="Research Loop",
            max_iterations=5,
            end_condition="all_success && current_iteration >= 2",
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
    print("Loop with CEL end condition: all_success && current_iteration >= 2")
    print("=" * 60)
    workflow.print_response(
        input="Research the impact of AI on healthcare",
        stream=True,
    )
