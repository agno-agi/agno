"""Router with CEL expression: route from session_state.
=====================================================

Uses session_state.preferred_handler to persist routing preferences
across workflow runs.

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
detailed_agent = Agent(
    name="Detailed Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You provide detailed, in-depth analysis with examples and data.",
    markdown=True,
)

brief_agent = Agent(
    name="Brief Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You provide brief, executive-summary style analysis. Keep it short.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="CEL Session State Router",
    steps=[
        Router(
            name="Analysis Style Router",
            selector="session_state.preferred_handler",
            choices=[
                Step(name="Detailed Analyst", agent=detailed_agent),
                Step(name="Brief Analyst", agent=brief_agent),
            ],
        ),
    ],
    session_state={"preferred_handler": "Brief Analyst"},
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Using session_state preference: Brief Analyst ---")
    workflow.print_response(input="Analyze the current state of cloud computing.")
    print()

    # Change preference
    workflow.session_state["preferred_handler"] = "Detailed Analyst"
    print("--- Changed preference to: Detailed Analyst ---")
    workflow.print_response(input="Analyze the current state of cloud computing.")
