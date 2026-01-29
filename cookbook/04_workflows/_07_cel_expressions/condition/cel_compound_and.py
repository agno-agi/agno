"""Condition with CEL: compound expression using && operator.

Combines input content check with additional_data priority
to gate a step behind multiple conditions.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

escalation_agent = Agent(
    name="Escalation Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="This is a high-priority escalation. Respond with urgency and provide immediate action items.",
    markdown=True,
)

standard_agent = Agent(
    name="Standard Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Handle this request through standard processing.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Compound AND Condition",
    steps=[
        Condition(
            name="Escalation Gate",
            evaluator='input.contains("urgent") && additional_data.priority > 7',
            steps=[
                Step(name="Escalate", agent=escalation_agent),
            ],
            else_steps=[
                Step(name="Standard", agent=standard_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Urgent + high priority (both conditions met) ---")
    workflow.print_response(
        input="This is an urgent security issue.",
        additional_data={"priority": 9},
    )
    print()

    print("--- Urgent but low priority (only one condition met) ---")
    workflow.print_response(
        input="This is an urgent but minor issue.",
        additional_data={"priority": 3},
    )
