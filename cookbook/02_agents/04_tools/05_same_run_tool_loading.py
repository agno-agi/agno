"""
Same-Run Tool Loading
====================

Load a tool on demand and use it in the next model iteration of the same run.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext


def multiply(left: int, right: int, run_context: RunContext) -> str:
    """Multiply two integers and report the session performing the calculation."""
    return f"{left * right} (session: {run_context.session_id})"


def load_calculator(agent: Agent) -> str:
    """Make the multiplication tool available for this run and future runs."""
    agent.add_tool(multiply)
    return "The multiply tool is available. Use it now to perform the calculation."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="On-Demand Calculator",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[load_calculator],
    instructions=[
        "Use the multiplication tool for arithmetic.",
        "If that tool is unavailable, call load_calculator, then multiply in the same run.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is 7 multiplied by 8?", stream=True)
