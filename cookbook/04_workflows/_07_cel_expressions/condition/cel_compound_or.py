"""Condition with CEL: compound expression using || operator.

Routes to a specialized handler if the input contains any of
several trigger keywords.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

safety_agent = Agent(
    name="Safety Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="This request has been flagged for safety review. Respond carefully and follow safety protocols.",
    markdown=True,
)

general_agent = Agent(
    name="General Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Handle this general request helpfully.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Compound OR Condition",
    steps=[
        Condition(
            name="Safety Check",
            evaluator='input.contains("error") || input.contains("critical") || input.contains("failure")',
            steps=[
                Step(name="Safety Review", agent=safety_agent),
            ],
            else_steps=[
                Step(name="General Handler", agent=general_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Contains 'critical' ---")
    workflow.print_response(input="We have a critical database outage.")
    print()

    print("--- No trigger keywords ---")
    workflow.print_response(input="How do I reset my password?")
