"""Condition with CEL: check previous_step_contents list.

Uses previous_step_contents.size() to check how many prior
steps produced output, gating a summary step.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Condition, Parallel, Step, Workflow

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

researcher_a = Agent(
    name="Researcher A",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the topic from an economic perspective.",
    markdown=True,
)

researcher_b = Agent(
    name="Researcher B",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research the topic from a technology perspective.",
    markdown=True,
)

synthesizer = Agent(
    name="Synthesizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Synthesize multiple research perspectives into a unified analysis.",
    markdown=True,
)

insufficient_agent = Agent(
    name="Insufficient Data",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Not enough research data was gathered. Suggest what additional research is needed.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Previous Step Contents Check",
    steps=[
        Parallel(
            Step(name="Economic Research", agent=researcher_a),
            Step(name="Tech Research", agent=researcher_b),
            name="Parallel Research",
        ),
        Condition(
            name="Enough Research",
            evaluator="previous_step_contents.size() >= 2",
            steps=[
                Step(name="Synthesize", agent=synthesizer),
            ],
            else_steps=[
                Step(name="Insufficient", agent=insufficient_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response(input="Analyze the impact of AI on the job market.")
