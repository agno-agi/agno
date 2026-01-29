"""Loop with CEL end condition: check step_contents list.

Uses step_contents.size() to verify all steps produced output
before stopping the loop.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Loop, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

interviewer = Agent(
    name="Interviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Generate an interview question about the topic.",
    markdown=True,
)

responder = Agent(
    name="Responder",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Answer the interview question from the previous step thoughtfully.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Step Contents Loop",
    steps=[
        Loop(
            name="Interview Loop",
            max_iterations=5,
            # Stop when both steps produced non-empty output
            end_condition="step_contents.size() >= 2 && all_success",
            steps=[
                Step(name="Ask", agent=interviewer),
                Step(name="Answer", agent=responder),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Loop with CEL end condition: step_contents.size() >= 2 && all_success")
    print("=" * 60)
    workflow.print_response(
        input="Interview about best practices in software engineering",
        stream=True,
    )
