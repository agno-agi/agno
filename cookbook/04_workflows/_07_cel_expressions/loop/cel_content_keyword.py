"""Loop with CEL end condition: stop when output contains a keyword.

Uses last_content.contains("DONE") so the agent can signal
completion through its output.

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
    instructions=(
        "You are a project planner. Break down the task into steps. "
        "When you have a complete plan, end your response with the word DONE."
    ),
    markdown=True,
)

workflow = Workflow(
    name="CEL Keyword Loop",
    steps=[
        Loop(
            name="Planning Loop",
            max_iterations=5,
            end_condition='last_content.contains("DONE")',
            steps=[
                Step(name="Plan", agent=planner),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print('Loop with CEL end condition: last_content.contains("DONE")')
    print("=" * 60)
    workflow.print_response(
        input="Create a plan for building a REST API with authentication",
        stream=True,
    )
