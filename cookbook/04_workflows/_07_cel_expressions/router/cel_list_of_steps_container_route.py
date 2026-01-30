"""Router with CEL expression: route to a Steps container (sequential steps).

Demonstrates how to use CEL to route to either a single step or a group of
sequential steps wrapped in a Steps container. Since CEL returns step names
as strings, we use the Steps container's name for routing.

Use case: Route between a quick single-step path vs a multi-step pipeline.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router
from agno.workflow.steps import Steps

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

# Single quick analysis step
quick_analyzer = Agent(
    name="Quick Analyzer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Provide a brief 2-3 sentence analysis. Be concise.",
    markdown=True,
)

# Multi-step deep analysis pipeline
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Research and gather key facts about the topic. List 3-5 important points.",
    markdown=True,
)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Based on the research provided, perform deep analysis. Identify patterns and insights.",
    markdown=True,
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Summarize the analysis into a clear, actionable conclusion.",
    markdown=True,
)

# Create the workflow with Router
# - "Quick Analysis" routes to a single step
# - "Deep Analysis Pipeline" routes to a Steps container with 3 sequential steps
workflow = Workflow(
    name="CEL Steps Container Router",
    steps=[
        Router(
            name="Analysis Depth Router",
            # CEL expression: route based on additional_data.mode
            # Returns either "Quick Analysis" or "Deep Analysis Pipeline"
            selector='additional_data.mode == "quick" ? "Quick Analysis" : "Deep Analysis Pipeline"',
            choices=[
                # Single step option
                Step(name="Quick Analysis", agent=quick_analyzer),
                # Steps container option - executes researcher -> analyst -> summarizer sequentially
                Steps(
                    name="Deep Analysis Pipeline",
                    steps=[
                        Step(name="Research", agent=researcher),
                        Step(name="Analyze", agent=analyst),
                        Step(name="Summarize", agent=summarizer),
                    ],
                ),
            ],
        ),
    ],
)

if __name__ == "__main__":
    topic = "The impact of AI on software development"

    print("=" * 60)
    print("QUICK MODE - Single step analysis")
    print("=" * 60)
    workflow.print_response(
        input=topic,
        additional_data={"mode": "quick"},
    )

    print("\n")
    print("=" * 60)
    print("DEEP MODE - Multi-step pipeline (Research -> Analyze -> Summarize)")
    print("=" * 60)
    workflow.print_response(
        input=topic,
        additional_data={"mode": "deep"},
    )
