"""Loop with CEL end condition: compound check on num_steps and success.

Uses num_steps with all_success to ensure all expected steps
ran and succeeded before stopping.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

planner = Agent(
    name="Planner",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Create a structured plan for the given task.",
    markdown=True,
)

executor = Agent(
    name="Executor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Execute the plan from the previous step. Report on results.",
    markdown=True,
)

reviewer = Agent(
    name="Reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Review the execution results. Confirm completeness.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Num Steps Loop",
    steps=[
        Loop(
            name="Plan-Execute-Review",
            max_iterations=3,
            # Stop when all 3 steps ran and all succeeded
            end_condition="num_steps >= 3 && all_success",
            steps=[
                Step(name="Plan", agent=planner),
                Step(name="Execute", agent=executor),
                Step(name="Review", agent=reviewer),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: num_steps >= 3 && all_success")
    print("=" * 60)
    workflow.print_response(
        input="Organize a team offsite event",
        stream=True,
    )
