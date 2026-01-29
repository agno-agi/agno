"""Loop with CEL end condition: stop when total output is large enough.

Uses total_content_length to stop the loop once the combined
output across all steps exceeds a threshold.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the given topic. Add new findings each time.",
    markdown=True,
)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Analyze the research and provide insights.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Total Content Length Loop",
    steps=[
        Loop(
            name="Research Loop",
            max_iterations=5,
            end_condition="total_content_length > 500",
            steps=[
                Step(name="Research", agent=researcher),
                Step(name="Analyze", agent=analyst),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: total_content_length > 500")
    print("=" * 60)
    workflow.print_response(
        input="Research the benefits of remote work",
        stream=True,
    )
