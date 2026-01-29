"""Condition with CEL: access nested additional_data fields.

Uses additional_data.user.role to route based on user role
passed from the application layer.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

admin_agent = Agent(
    name="Admin Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are responding to an admin user. Provide full access to all features and detailed system information.",
    markdown=True,
)

user_agent = Agent(
    name="User Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are responding to a regular user. Provide helpful but appropriately scoped information.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Nested Data Condition",
    steps=[
        Condition(
            name="Role Check",
            evaluator='additional_data.user.role == "admin"',
            steps=[
                Step(name="Admin Response", agent=admin_agent),
            ],
            else_steps=[
                Step(name="User Response", agent=user_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Admin user ---")
    workflow.print_response(
        input="Show me the system status.",
        additional_data={"user": {"role": "admin", "name": "Alice"}},
    )
    print()

    print("--- Regular user ---")
    workflow.print_response(
        input="Show me the system status.",
        additional_data={"user": {"role": "viewer", "name": "Bob"}},
    )
