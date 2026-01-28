"""Loop with CEL end condition: stop when content is substantial.

Uses max_content_length > 200 to stop the loop once any step
produces enough output, mirroring the common callable pattern.

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
    instructions="Research the given topic thoroughly.",
    markdown=True,
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Summarize the research findings concisely.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Content Length Loop",
    steps=[
        Loop(
            name="Research Loop",
            max_iterations=3,
            end_condition="max_content_length > 200",
            steps=[
                Step(name="Research", agent=researcher),
                Step(name="Summarize", agent=summarizer),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: max_content_length > 200")
    print("=" * 60)
    workflow.print_response(
        input="Research the latest developments in quantum computing",
        stream=True,
    )
