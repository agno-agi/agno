"""
Intent Routing With History
===========================

Demonstrates simple intent routing where all specialist steps share workflow history for context continuity.
"""

from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
tech_support_agent = Agent(
    name="Technical Support Specialist",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a technical support specialist with deep product knowledge.",
        "You have access to the full conversation history with this customer.",
        "Reference previous interactions to provide better help.",
        "Build on any troubleshooting steps already attempted.",
        "Be patient and provide step-by-step technical guidance.",
    ],
)

billing_agent = Agent(
    name="Billing & Account Specialist",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a billing and account specialist.",
        "You have access to the full conversation history with this customer.",
        "Reference any account details or billing issues mentioned previously.",
        "Build on any payment or account information already discussed.",
        "Be helpful with billing questions, refunds, and account changes.",
    ],
)

general_support_agent = Agent(
    name="General Customer Support",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a general customer support representative.",
        "You have access to the full conversation history with this customer.",
        "Handle general inquiries, product information, and basic support.",
        "Reference the conversation context - build on what was discussed.",
        "Be friendly and acknowledge their previous interactions.",
    ],
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
tech_support_step = Step(
    name="Technical Support",
    agent=tech_support_agent,
    add_workflow_history=True,
)

billing_support_step = Step(
    name="Billing Support",
    agent=billing_agent,
    add_workflow_history=True,
)

general_support_step = Step(
    name="General Support",
    agent=general_support_agent,
    add_workflow_history=True,
)


# ---------------------------------------------------------------------------
# Define Router
# ---------------------------------------------------------------------------
def simple_intent_router(step_input: StepInput) -> List[Step]:
    current_message = step_input.input or ""
    current_message_lower = current_message.lower()

    tech_keywords = [
        "api",
        "error",
        "bug",
        "technical",
        "login",
        "not working",
        "broken",
        "crash",
    ]
    billing_keywords = [
        "billing",
        "payment",
        "refund",
        "charge",
        "subscription",
        "invoice",
        "plan",
    ]

    if any(keyword in current_message_lower for keyword in tech_keywords):
        print("Routing to Technical Support")
        return [tech_support_step]
    if any(keyword in current_message_lower for keyword in billing_keywords):
        print("Routing to Billing Support")
        return [billing_support_step]

    print("Routing to General Support")
    return [general_support_step]


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
def create_smart_customer_service_workflow() -> Workflow:
    return Workflow(
        name="Smart Customer Service",
        description="Simple routing to specialists with shared conversation history",
        db=SqliteDb(db_file="tmp/smart_customer_service.db"),
        steps=[
            Router(
                name="Customer Service Router",
                selector=simple_intent_router,
                choices=[tech_support_step, billing_support_step, general_support_step],
                description="Routes to appropriate specialist based on simple intent detection",
            )
        ],
        add_workflow_history_to_steps=True,
    )


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
def demo_smart_customer_service_cli() -> None:
    workflow = create_smart_customer_service_workflow()

    print("Smart Customer Service Demo")
    print("=" * 60)
    print("")
    print("This workflow demonstrates:")
    print("- Simple routing between Technical, Billing, and General support")
    print("- Shared conversation history across all agents")
    print("- Context continuity - agents remember your entire conversation")
    print("")
    print("TRY THESE CONVERSATIONS:")
    print("")
    print("TECHNICAL SUPPORT:")
    print("   - 'My API is not working'")
    print("   - 'I'm getting an error message'")
    print("   - 'There's a technical bug'")
    print("")
    print("BILLING SUPPORT:")
    print("   - 'I need help with billing'")
    print("   - 'Can I get a refund?'")
    print("   - 'My payment was charged twice'")
    print("")
    print("GENERAL SUPPORT:")
    print("   - 'Hello, I have a question'")
    print("   - 'What features do you offer?'")
    print("   - 'I need general help'")
    print("")
    print("Type 'exit' to quit")
    print("-" * 60)

    workflow.cli_app(
        session_id="smart_customer_service_demo",
        user="Customer",
        emoji="",
        stream=True,
        show_step_details=True,
    )


if __name__ == "__main__":
    demo_smart_customer_service_cli()
