"""Loop with CEL end condition: compound exit with content and iteration.

Combines content quality check with iteration progress to stop
the loop when output is good enough OR we've iterated enough.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write or refine an article on the given topic. Make each draft better than the last.",
    markdown=True,
)

editor = Agent(
    name="Editor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Edit and improve the article. If it is publication-ready, say APPROVED.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Compound Exit Loop",
    steps=[
        Loop(
            name="Write-Edit Loop",
            max_iterations=5,
            # Stop if content is long enough OR we've done at least 2 iterations with success
            end_condition="max_content_length > 300 || (iteration >= 2 && all_success)",
            steps=[
                Step(name="Write", agent=writer),
                Step(name="Edit", agent=editor),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL: max_content_length > 300 || (iteration >= 2 && all_success)")
    print("=" * 60)
    workflow.print_response(
        input="Write an article about the future of space tourism",
        stream=True,
    )
