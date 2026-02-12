"""Condition with CEL expression: branching on previous step output.
=================================================================

Runs a classifier step first, then uses previous_step_content.contains()
to decide the next step.

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
classifier = Agent(
    name="Classifier",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "Classify the request as either TECHNICAL or GENERAL. "
        "Respond with exactly one word: TECHNICAL or GENERAL."
    ),
    markdown=False,
)

technical_agent = Agent(
    name="Technical Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a technical support specialist. Provide detailed technical help.",
    markdown=True,
)

general_agent = Agent(
    name="General Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle general inquiries. Be friendly and helpful.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Classify and Route",
    steps=[
        Step(name="Classify", agent=classifier),
        Condition(
            name="Route by Classification",
            evaluator='previous_step_content.contains("TECHNICAL")',
            steps=[
                Step(name="Technical Help", agent=technical_agent),
            ],
            else_steps=[
                Step(name="General Help", agent=general_agent),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Technical question ---")
    workflow.print_response(
        input="My API returns 500 errors when I send POST requests with JSON payloads."
    )
    print()

    print("--- General question ---")
    workflow.print_response(input="What are your business hours?")
