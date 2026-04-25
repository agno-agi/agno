"""Router with CEL: route using step_choices index.
================================================

Uses step_choices[0], step_choices[1], etc. to reference steps by their
position in the choices list, rather than hardcoding step names.

This is useful when you want to:
- Avoid typos in step names
- Make the CEL expression more maintainable
- Reference steps dynamically based on index

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
quick_analyzer = Agent(
    name="Quick Analyzer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Provide a brief, concise analysis of the topic.",
    markdown=True,
)

detailed_analyzer = Agent(
    name="Detailed Analyzer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Provide a comprehensive, in-depth analysis of the topic.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Step Choices Router",
    steps=[
        Router(
            name="Analysis Router",
            # step_choices[0] = "Quick Analysis" (first choice)
            # step_choices[1] = "Detailed Analysis" (second choice)
            selector='input.contains("quick") || input.contains("brief") ? step_choices[0] : step_choices[1]',
            choices=[
                Step(name="Quick Analysis", agent=quick_analyzer),
                Step(name="Detailed Analysis", agent=detailed_analyzer),
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # This will route to step_choices[0] ("Quick Analysis")
    print("=== Quick analysis request ===")
    workflow.print_response(
        input="Give me a quick overview of quantum computing.", stream=True
    )

    print("\n" + "=" * 50 + "\n")

    # This will route to step_choices[1] ("Detailed Analysis")
    print("=== Detailed analysis request ===")
    workflow.print_response(input="Explain quantum computing in detail.", stream=True)
