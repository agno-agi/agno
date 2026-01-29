"""Router with CEL: route based on previous step output.

A classifier step runs first, then the router uses
previous_step_content to select the appropriate handler.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

classifier = Agent(
    name="Classifier",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=(
        "Classify the request into exactly one category. "
        "Respond with only one word: BILLING, TECHNICAL, or GENERAL."
    ),
    markdown=False,
)

billing_agent = Agent(
    name="Billing Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle billing inquiries. Help with invoices, payments, and subscriptions.",
    markdown=True,
)

technical_agent = Agent(
    name="Technical Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle technical issues. Help with debugging and configuration.",
    markdown=True,
)

general_agent = Agent(
    name="General Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You handle general inquiries.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Previous Step Router",
    steps=[
        Step(name="Classify", agent=classifier),
        Router(
            name="Support Router",
            selector=(
                'previous_step_content.contains("BILLING") ? "Billing Support" : '
                'previous_step_content.contains("TECHNICAL") ? "Technical Support" : '
                '"General Support"'
            ),
            choices=[
                Step(name="Billing Support", agent=billing_agent),
                Step(name="Technical Support", agent=technical_agent),
                Step(name="General Support", agent=general_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Billing question ---")
    workflow.print_response(input="I was charged twice on my last invoice.")
    print()

    print("--- Technical question ---")
    workflow.print_response(input="My API keeps returning 503 errors.")
