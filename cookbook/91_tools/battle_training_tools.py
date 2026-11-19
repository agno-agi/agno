"""
Battle Training Tools
=============================

Demonstrates battle training tools.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.battle_training import BattleTrainingTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    tools=[BattleTrainingTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Who are the top 5 bots on the battle.training public ladder, and how is the "
        "bot 'kimmy' doing in the November Cup?",
        stream=True,
    )
