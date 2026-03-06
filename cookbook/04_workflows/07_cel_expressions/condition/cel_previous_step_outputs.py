"""Condition with CEL: branch based on a named step's output.
==========================================================

Uses previous_step_outputs map to check the output of a specific
step by name, enabling multi-step pipelines with conditional logic.

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
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the topic. If the topic involves safety risks, include SAFETY_REVIEW_NEEDED in your response.",
    markdown=True,
)

safety_reviewer = Agent(
    name="Safety Reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Review the research for safety concerns and provide recommendations.",
    markdown=True,
)

publisher = Agent(
    name="Publisher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Prepare the research for publication.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Previous Step Outputs Condition",
    steps=[
        Step(name="Research", agent=researcher),
        Condition(
            name="Safety Check",
            # Check the Research step output by name
            evaluator='previous_step_outputs.Research.contains("SAFETY_REVIEW_NEEDED")',
            steps=[
                Step(name="Safety Review", agent=safety_reviewer),
            ],
        ),
        Step(name="Publish", agent=publisher),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Safe topic (skips safety review) ---")
    workflow.print_response(input="Write about gardening tips for beginners.")
    print()

    print("--- Safety-sensitive topic (triggers safety review) ---")
    workflow.print_response(
        input="Write about handling hazardous chemicals in a home lab."
    )
