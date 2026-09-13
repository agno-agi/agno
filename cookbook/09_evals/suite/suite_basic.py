"""
Eval Suite
==========

Declare a few Cases and run them as a suite with the built-in CLI.

python cookbook/09_evals/suite/suite_basic.py                 # run all cases
python cookbook/09_evals/suite/suite_basic.py --list          # list cases
python cookbook/09_evals/suite/suite_basic.py --tag smoke     # run a tagged subset
python cookbook/09_evals/suite/suite_basic.py --json-output tmp/evals.json
"""

import sys

from agno.agent import Agent
from agno.eval import Case, cli
from agno.models.openai import OpenAIResponses
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="math-tutor",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[CalculatorTools()],
    instructions="Use the calculator tools for any arithmetic.",
)

# ---------------------------------------------------------------------------
# Declare Cases
# ---------------------------------------------------------------------------
CASES = (
    Case(
        name="factorial_uses_calculator",
        agent=agent,
        input="What is 10! (ten factorial)?",
        tags=("smoke",),
        criteria="States that 10! equals 3628800.",
        expected_tool_calls=("factorial",),
    ),
    Case(
        name="explains_compound_interest",
        agent=agent,
        input="Explain compound interest in one short paragraph.",
        criteria="Explains that interest is earned on both the principal and previously earned interest.",
    ),
)

# ---------------------------------------------------------------------------
# Run Suite
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sys.exit(cli(CASES))
