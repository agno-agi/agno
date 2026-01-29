"""Loop with CEL end condition: stop on any failure.

Uses any_failure to break the loop immediately when
any step in the iteration fails.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

data_fetcher = Agent(
    name="Data Fetcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Fetch and present data about the given topic.",
    markdown=True,
)

validator = Agent(
    name="Validator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Validate the data from the previous step for accuracy and completeness.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Any Failure Loop",
    steps=[
        Loop(
            name="Fetch and Validate",
            max_iterations=5,
            end_condition="any_failure",
            steps=[
                Step(name="Fetch", agent=data_fetcher),
                Step(name="Validate", agent=validator),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: any_failure")
    print("=" * 60)
    workflow.print_response(
        input="Gather statistics on global renewable energy adoption",
        stream=True,
    )
