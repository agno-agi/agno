"""
Battle Training Tools
=============================

Demonstrates the battle.training arena tools: public ladder standings, bot
profiles, cup standings and the standings by coding agent.

battle.training is a tactical combat arena where AI coding agents write
JavaScript controllers that fight around the clock. The endpoints are public,
so no account or API key is needed.

Read more: https://battle.training
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.battle_training import BattleTrainingTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

arena_agent = Agent(
    name="Arena Analyst",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[BattleTrainingTools()],
    description="You are an analyst for the battle.training arena, where AI coding agents write the bots that fight.",
    instructions=[
        "Use get_arena_status for a quick overview of the arena before answering broad questions.",
        "Use get_ladder and get_agent_standings to say who is winning, and name the agent and model behind each bot.",
        "Use get_bot to inspect one bot's standings, active version health and recent matches.",
        "Use get_ladders and get_ladder_standings for cups and side ladders.",
        "Ratings are Bradley-Terry, refit hourly; quote the retrieval time when you cite a ranking.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    arena_agent.print_response(
        "Who is winning the battle.training ladder right now, and which coding agent wrote the top bot?"
    )
