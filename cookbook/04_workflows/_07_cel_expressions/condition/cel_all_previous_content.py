"""Condition with CEL expression: using all_previous_content.

Uses all_previous_content to check concatenated content from all previous steps.
This is useful when you need to analyze the full context of what happened before.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the topic and provide key findings. Be thorough.",
    markdown=True,
)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Analyze the research findings and identify patterns or insights.",
    markdown=True,
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Create a brief executive summary of the findings.",
    markdown=True,
)

detailed_reporter = Agent(
    name="Detailed Reporter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Create a comprehensive detailed report with all findings and analysis.",
    markdown=True,
)

workflow = Workflow(
    name="CEL All Previous Content",
    steps=[
        Step(name="Research", agent=researcher),
        Step(name="Analyze", agent=analyst),
        # Check if combined content from all previous steps is substantial
        Condition(
            name="Content Length Check",
            evaluator='all_previous_content.size() > 500',
            steps=[
                Step(name="Create Summary", agent=summarizer),
            ],
            else_steps=[
                Step(name="Create Detailed Report", agent=detailed_reporter),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("Workflow with CEL all_previous_content check")
    print("=" * 60)
    print("If combined previous content > 500 chars: summarize")
    print("Otherwise: create detailed report")
    print("=" * 60)
    workflow.print_response(
        input="Research the impact of AI on healthcare",
        stream=True,
    )
