"""Router with CEL expression: route from additional_data field.
=============================================================

Uses additional_data.route to let the caller specify which step
to run, useful when the routing decision is made upstream (e.g. UI).

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
email_agent = Agent(
    name="Email Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You write professional emails. Be concise and polished.",
    markdown=True,
)

blog_agent = Agent(
    name="Blog Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You write engaging blog posts with clear structure and headings.",
    markdown=True,
)

tweet_agent = Agent(
    name="Tweet Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You write punchy tweets. Keep it under 280 characters.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Additional Data Router",
    steps=[
        Router(
            name="Content Format Router",
            selector="additional_data.route",
            choices=[
                Step(name="Email Writer", agent=email_agent),
                Step(name="Blog Writer", agent=blog_agent),
                Step(name="Tweet Writer", agent=tweet_agent),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Route to email ---")
    workflow.print_response(
        input="Write about our new product launch.",
        additional_data={"route": "Email Writer"},
    )
    print()

    print("--- Route to tweet ---")
    workflow.print_response(
        input="Write about our new product launch.",
        additional_data={"route": "Tweet Writer"},
    )
