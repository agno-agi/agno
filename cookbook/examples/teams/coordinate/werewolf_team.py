import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.models.deepseek.deepseek import DeepSeek
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# Create player agents (no separate moderator)
player_agents = []
for i in range(1, 7):
    player_agents.append(
        Agent(
            name=f"Player{i}",
            role="Werewolf Game Player",
            model=OpenAIChat(id="gpt-4o-mini"),
            add_name_to_instructions=True,
            instructions=dedent(f"""
            You are Player{i} in a simplified Werewolf game.
            The game moderator will tell you your role (villager or imposter).

            If you're a villager:
            - Try to identify the imposters through deduction and discussion
            - Vote to eliminate suspected imposters during day phase

            If you're an imposter:
            - Try to eliminate villagers without being detected
            - Pretend to be a villager in public discussions
            - During night phase, coordinate with other imposters to eliminate a villager

            Be strategic, observant, and adapt your gameplay based on others' behaviors.

            Add emojis to express your emotions and thoughts.
            """),
        )
    )

# Create the team (serves as the moderator)
werewolf_team = Team(
    name="Werewolf Game",
    mode="coordinate",
    model=Claude(id="claude-3-5-sonnet-20241022"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    success_criteria="The game ends with either villagers or imposters winning. Don't stop the game until the end!",
    members=player_agents,
    instructions=[
        "You are the moderator of a simplified Werewolf game with 6 players.",
        "The game has 2 imposters and 4 villagers, randomly assigned.",
        # Moderator responsibilities
        "As the moderator, you must:",
        "- Keep track of all player roles and game state",
        "- Privately inform each player of their role",
        "- Facilitate day and night phases",
        "- Track votes and eliminations",
        "- Announce results and enforce rules",
        "- Be careful not to leak role information in public discussions",
        # Setup phase
        "First, initialize the game by creating the following game state and storing it in the team context:",
        "- Generate random roles (2 imposters, 4 villagers) and assign to players",
        "- Store player roles, alive players, game phase, and other state information",
        "- Privately inform each player of their role",
        "- For imposters, also tell them who the other imposters are",
        # Game flow
        "Run the game through alternating day and night phases:",
        "Day phase:",
        "- All players discuss and try to identify imposters (remember to add their discussion points to the team context)",
        "- Each player votes to eliminate someone (remember to add their vote to the team context)",
        "- The player with the most votes is eliminated",
        "- Update game state with elimination and check win conditions",
        "Night phase:",
        "- Privately ask the imposters which villager to eliminate",
        "- Imposters decide and eliminate one villager",
        "- Update game state with elimination and check win conditions",
        # Win conditions
        "The game ends when either:",
        "- All imposters are eliminated (villagers win)",
        "- Imposters equal or outnumber villagers (imposters win)",
        # Important rules
        "Critical rules to enforce:",
        "- Player roles must remain secret (only you as moderator know all roles)",
        "- Eliminated players cannot participate further",
        "- Track game state in the team context after each phase",
        "- Check win conditions after each elimination",
        "- Don't stop the game until the end! Continue corresponding with the players until the game is over.",
    ],
    enable_agentic_context=True,
    enable_team_history=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
    debug_mode=True,
)

# Run the game
asyncio.run(
    werewolf_team.aprint_response(
        message="Start a new Werewolf game. First plan how you will run the game. Then assign roles and initialize the game state. Then proceed with the first day phase and continue until the game is over.",
        stream=True,
        stream_intermediate_steps=True,
    )
)
