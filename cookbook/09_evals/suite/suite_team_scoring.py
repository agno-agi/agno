"""
Eval Suite: Team with Numeric Judge Scoring
===========================================

Run a Team through the suite - the leader delegates to its members - and grade every
answer with a numeric 1-10 judge.

python cookbook/09_evals/suite/suite_team_scoring.py                 # run all cases
python cookbook/09_evals/suite/suite_team_scoring.py --list          # list cases
python cookbook/09_evals/suite/suite_team_scoring.py --tag smoke     # run a tagged subset
python cookbook/09_evals/suite/suite_team_scoring.py --json-output tmp/evals.json
"""

import sys

from agno.agent import Agent
from agno.eval import Case, JudgeMode, cli
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create the Team and its members
# ---------------------------------------------------------------------------
calculator = Agent(
    id="calculator",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[CalculatorTools()],
    instructions="Use the calculator tools for every arithmetic operation. Never compute arithmetic yourself.",
)
writer = Agent(
    id="writer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer in one clear paragraph.",
)
assistant_team = Team(
    id="assistant-team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[calculator, writer],
    instructions="Delegate arithmetic to the calculator member and writing to the writer member, then report the member's result.",
)

# ---------------------------------------------------------------------------
# Declare Cases - both run against the Team
# ---------------------------------------------------------------------------
CASES = (
    Case(
        name="team_uses_calculator",
        team=assistant_team,
        input="What is 4891 multiplied by 7238?",
        tags=("smoke",),
        criteria="States that the product is 35,401,058.",
        judge_mode=JudgeMode.NUMERIC,
        judge_threshold=7,
        expected_tool_calls=("multiply",),
    ),
    Case(
        name="team_explains_clearly",
        team=assistant_team,
        input="Explain compound interest in one paragraph.",
        criteria="Explains that interest is earned on both the principal and previously earned interest.",
        judge_mode=JudgeMode.NUMERIC,
        judge_threshold=7,
    ),
)

# ---------------------------------------------------------------------------
# Run Suite
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sys.exit(cli(CASES))
