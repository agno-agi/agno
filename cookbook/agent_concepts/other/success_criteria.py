from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.reasoning import ReasoningTools

puzzle_master = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[ReasoningTools(add_instructions=True)],
    instructions=dedent("""\
    You are a puzzle master who creates and solves logic puzzles.
    - Create clear puzzles with unique solutions
    - Solve systematically using logical deduction
    - Verify all clues are satisfied
    - Show your reasoning step-by-step\
    """),
    success_criteria=dedent("""\
    The puzzle must be:
    1. Completely solved with a unique, correct solution
    2. All clues satisfied and verified
    3. Solution process clearly explained with logical reasoning
    4. Final answer explicitly stated in a clear format\
    """),
    markdown=True,
)

puzzle = """\
Create and solve this logic puzzle:

Three friends—Alice, Bob, and Carol—each choose a different drink from tea, coffee, and milk.

CLUES:
1. Alice does not drink tea.
2. The person who drinks coffee is not Carol.

Present the final answer as: "Alice drinks X, Bob drinks Y, Carol drinks Z"\
"""

puzzle_master.print_response(
    puzzle,
    stream=True,
    show_full_reasoning=True,
    stream_intermediate_steps=True,
)
