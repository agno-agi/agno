"""Battle Training MCP Agent - Scout the Arena Where AI Bots Fight

Connect an Agno agent to battle.training's hosted MCP server. battle.training
is an arena where AI agents write bot controllers and fight rated ladder
matches in three theaters (Armor, Air and Silent Service), with a verifiable
replay for every set.

The server's read tools are public, so the default flow needs no
battle.training account: the agent reads the live ladder, inspects a bot's
rank, rating and recent sets, and lists the theaters and cups. The write tools
(creating bots, uploading controller versions, enrolling in a ladder) act on
your own account; they are only included when `BATTLE_TRAINING_API_KEY` is
set, and the key is sent as a bearer header, never as a tool argument.

Setup:
1. Install dependencies: `uv pip install "agno[mcp,openai]"`
2. Set `OPENAI_API_KEY` in your environment
3. Optional, for the write tools: create an account at https://battle.training
   and set `BATTLE_TRAINING_API_KEY`

Run: `python cookbook/91_tools/mcp/battle_training.py`

battle.training MCP docs: https://battle.training/llms.txt
"""

import asyncio
from os import getenv
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools

BATTLE_TRAINING_MCP_URL = "https://api.battle.training/mcp"

# Public read tools: no account key required.
READ_TOOLS = [
    "get_started",
    "controller_api",
    "get_starter",
    "get_starter_sub",
    "get_rules",
    "get_bot",
    "get_ladder",
    "list_matches",
    "get_match",
    "list_ladders",
    "get_cup",
    "get_live",
]

# Write tools: act on the caller's account, included only with an API key.
WRITE_TOOLS = [
    "create_bot",
    "upload_version",
    "enrol_ladder",
    "scrimmage",
    "set_payout_wallet",
]


async def run_agent(task: str) -> None:
    """Connect to battle.training and run one scouting task."""
    api_key = getenv("BATTLE_TRAINING_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    include_tools = READ_TOOLS + WRITE_TOOLS if api_key else READ_TOOLS

    async with MCPTools(
        url=BATTLE_TRAINING_MCP_URL,
        transport="streamable-http",
        headers=headers,
        include_tools=include_tools,
    ) as battle_tools:
        agent = Agent(
            name="BattleScoutAgent",
            model=OpenAIResponses(id="gpt-5.6-luna"),
            tools=[battle_tools],
            markdown=True,
            instructions=dedent("""\
                You scout battle.training, the arena where AI agents fight
                rated bot battles, using its MCP tools.

                - Ground every claim in a tool result: read the ladder before
                  ranking bots, and read a bot before describing its record
                - get_bot takes the bot's name, not an id; get_ladder returns
                  the Armor ladder, and list_ladders shows every theater and
                  cup, including the emptier Air and Silent Service ladders
                - Ratings carry an RD (rating deviation): a high RD means the
                  rating is still uncertain, so say so instead of treating it
                  as exact
                - The ladder ranks bot controllers, not the models behind
                  them; never present it as an official model benchmark
                - Write tools (create_bot, upload_version, enrol_ladder,
                  scrimmage) act on the user's own account and are only
                  available when they provided an API key; never invent one
            """),
        )
        await agent.aprint_response(input=task, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Scout the Armor ladder: who are the top five bots right now, and "
            "how is the bot delynn-prime doing - its rank, rating and record?"
        )
    )

# More example queries:
"""
- "Which ladders and cups are running right now, and which theater is the emptiest?"
- "Compare delynn-prime in Armor with delynn-pyong in Air: rank, rating, RD and record for each."
- "Show the latest sets played by delynn-pyong and summarize how they went."
- "What are the current standings in the November Cup?"
"""
