"""Loop with CEL end condition: stop on first success.

Uses all_success to break out of the loop as soon as all steps
in an iteration succeed.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Analyze the given topic and provide key insights.",
    markdown=True,
)

reviewer = Agent(
    name="Reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Review the analysis for completeness and accuracy.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Success Check Loop",
    steps=[
        Loop(
            name="Analysis Loop",
            max_iterations=5,
            end_condition="all_success",
            steps=[
                Step(name="Analyze", agent=analyst),
                Step(name="Review", agent=reviewer),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: all_success")
    print("=" * 60)
    workflow.print_response(
        input="Analyze the pros and cons of microservices architecture",
        stream=True,
    )
