"""Router with CEL: compound selector using && and ||.

Combines input content with additional_data to make a
routing decision.

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

premium_agent = Agent(
    name="Premium Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You provide premium, white-glove support. Be thorough and detailed.",
    markdown=True,
)

standard_agent = Agent(
    name="Standard Support",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You provide standard support. Be helpful and concise.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Compound Selector Router",
    steps=[
        Router(
            name="Support Tier Router",
            selector=(
                '(additional_data.tier == "premium" || input.contains("enterprise")) '
                '? "Premium Support" : "Standard Support"'
            ),
            choices=[
                Step(name="Premium Support", agent=premium_agent),
                Step(name="Standard Support", agent=standard_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Premium tier user ---")
    workflow.print_response(
        input="Help me set up SSO for my team.",
        additional_data={"tier": "premium"},
    )
    print()

    print("--- Standard tier but mentions enterprise ---")
    workflow.print_response(
        input="We need enterprise-grade security features.",
        additional_data={"tier": "standard"},
    )
    print()

    print("--- Standard tier, no keywords ---")
    workflow.print_response(
        input="How do I change my password?",
        additional_data={"tier": "standard"},
    )
