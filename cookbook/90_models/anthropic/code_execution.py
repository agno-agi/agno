"""
Anthropic Code Execution
========================

Cookbook example for `anthropic/code_execution.py`.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        betas=["code-execution-2025-05-22"],
    ),
    tools=[
        {
            "type": "code_execution_20250522",
            "name": "code_execution",
        }
    ],
    markdown=True,
)

agent.print_response(
    "Calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
    stream=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
