"""Router with CEL: route based on previous_step_contents list size.

Uses previous_step_contents.size() to choose between a synthesis
agent (multiple prior outputs) or a single-source agent.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Parallel, Step, Workflow
from agno.workflow.router import Router

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

researcher_a = Agent(
    name="Market Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research market trends for the given topic.",
    markdown=True,
)

researcher_b = Agent(
    name="Tech Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research technology developments for the given topic.",
    markdown=True,
)

synthesis_agent = Agent(
    name="Multi-Source Synthesis",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Synthesize findings from multiple research sources into a unified report.",
    markdown=True,
)

single_source_agent = Agent(
    name="Single Source Summary",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Summarize the single research source available.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Previous Step Contents Router",
    steps=[
        Parallel(
            Step(name="Market Research", agent=researcher_a),
            Step(name="Tech Research", agent=researcher_b),
            name="Parallel Research",
        ),
        Router(
            name="Synthesis Router",
            selector='previous_step_contents.size() > 1 ? "Multi-Source Synthesis" : "Single Source Summary"',
            choices=[
                Step(name="Multi-Source Synthesis", agent=synthesis_agent),
                Step(name="Single Source Summary", agent=single_source_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response(input="Analyze the electric vehicle market.")
