"""
CodeMode - Basic
================

Give the agent one programmable environment instead of a wide tool schema.
The model writes Python; the code runs in an IPython kernel that lives as long
as the session, so variables, imports, and helper functions survive across
turns.

The agent below computes over a list of numbers without any of the data
entering the transcript as text: it stays a variable in the kernel and only
the conclusion is printed.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.code import CodeMode

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
code = CodeMode()

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[code],
    instructions="Use the code environment to compute answers. Print summaries, not raw data.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        agent.print_response(
            "Build a list of the first 200 Fibonacci numbers in the code environment, "
            "keep it in a variable, and tell me only how many of them are even and "
            "how many digits the largest one has.",
            session_id="code-mode-basic",
        )
    finally:
        code.shutdown()
