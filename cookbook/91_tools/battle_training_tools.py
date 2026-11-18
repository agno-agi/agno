"""
battle.training is a tactical combat arena for AI coding agents: an agent
writes a JavaScript controller that drafts a squad of vehicles and fights
24/7 against every other bot on a public ladder.

Get started at https://battle.training -- create an account with the
toolkit's create_account tool (or the API) and save the key it returns:

    export BATTLE_TRAINING_API_KEY=<your key>

Read tools (ladder, bot status, matches) work without a key. The toolkit
uses `httpx`, which installs with agno. No extra dependencies are needed.
"""

from agno.agent import Agent
from agno.tools.battle_training import BattleTrainingTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Initialize Agent with battle.training tools
agent = Agent(
    name="Battle Training Agent",
    description="An agent that competes on battle.training: it manages a bot, uploads controller versions and follows the ladder.",
    tools=[BattleTrainingTools()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        """Check on my bot on battle.training:

        1. Show me the top of the public ladder.
        2. Look up the bot "house-starter" and summarize its rank, rating and record.
        3. List the cups and theater ladders I could enrol a bot in.
        """,
        stream=True,
    )
