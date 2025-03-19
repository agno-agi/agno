"""
Tic Tac Toe Battle
---------------------------------
This example shows how to build a Tic Tac Toe game where AI agents play different roles in a team.
The game features specialized agents for X and O players, and a referee agent coordinating the game.

Usage Examples:
---------------
1. Quick game with default settings:
   team = get_tic_tac_toe_team()

2. Game with debug mode off:
   team = get_tic_tac_toe_team(debug_mode=False)

The game integrates:
  - Multiple AI models (Claude, GPT-4, etc.)
  - Specialized agent roles (X player, O player, referee)
  - Turn-based gameplay coordination
  - Move validation and game state management
"""

import sys
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.utils.log import logger

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)


def get_model_for_provider(provider: str, model_name: str):
    """
    Creates and returns the appropriate model instance based on the provider.

    Args:
        provider: The model provider (e.g., 'openai', 'google', 'anthropic', 'groq')
        model_name: The specific model name/ID

    Returns:
        An instance of the appropriate model class

    Raises:
        ValueError: If the provider is not supported
    """
    if provider == "openai":
        return OpenAIChat(id=model_name)
    elif provider == "google":
        return Gemini(id=model_name)
    elif provider == "anthropic":
        if model_name == "claude-3-5-sonnet":
            return Claude(id="claude-3-5-sonnet-20241022", max_tokens=8192)
        elif model_name == "claude-3-7-sonnet":
            return Claude(
                id="claude-3-7-sonnet-20250219",
                max_tokens=8192,
            )
        elif model_name == "claude-3-7-sonnet-thinking":
            return Claude(
                id="claude-3-7-sonnet-20250219",
                max_tokens=8192,
                thinking={"type": "enabled", "budget_tokens": 4096},
            )
        else:
            return Claude(id=model_name)
    elif provider == "groq":
        return Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")


def get_tic_tac_toe_team(
    model_x: str = "openai:gpt-4o",
    model_o: str = "anthropic:claude-3-7-sonnet",
    referee_model: str = "openai:gpt-4o",
    debug_mode: bool = True,
) -> Team:
    """
    Returns a tic-tac-toe team with specialized agents for X player, O player, and referee.

    Args:
        model_x: Model for player X
        model_o: Model for player O
        referee_model: Model for game coordination and state evaluation
        debug_mode: Enable logging and debug features

    Returns:
        Team instance configured for tic-tac-toe gameplay
    """
    try:
        x_provider, x_name = model_x.split(":")
        o_provider, o_name = model_o.split(":")
        referee_provider, referee_name = referee_model.split(":")

        x_model = get_model_for_provider(x_provider, x_name)
        o_model = get_model_for_provider(o_provider, o_name)
        referee_model = get_model_for_provider(referee_provider, referee_name)

        player_x = Agent(
            name="Player X",
            role="X Player",
            model=x_model,
            description=dedent("""\
                You are Player X in a Tic Tac Toe game. Your goal is to win by placing three X's in a row.

                BOARD LAYOUT:
                - The board is a 3x3 grid with coordinates from (0,0) to (2,2)
                - Top-left is (0,0), bottom-right is (2,2)

                RULES:
                - You can only place X in empty spaces (shown as " " on the board)
                - Players take turns placing their marks
                - First to get 3 marks in a row (horizontal, vertical, or diagonal) wins
                - If all spaces are filled with no winner, the game is a draw

                YOUR RESPONSE:
                - Provide ONLY two numbers separated by a space (row column)
                - Example: "1 2" places your X in row 1, column 2
                - Choose only from the valid moves list provided to you

                STRATEGY TIPS:
                - Study the board carefully and make strategic moves
                - Block your opponent's potential winning moves
                - Create opportunities for multiple winning paths
                - Pay attention to the valid moves and avoid illegal moves"""),
            debug_mode=debug_mode,
        )

        player_o = Agent(
            name="Player O",
            role="O Player",
            model=o_model,
            description=dedent("""\
                You are Player O in a Tic Tac Toe game. Your goal is to win by placing three O's in a row.

                BOARD LAYOUT:
                - The board is a 3x3 grid with coordinates from (0,0) to (2,2)
                - Top-left is (0,0), bottom-right is (2,2)

                RULES:
                - You can only place O in empty spaces (shown as " " on the board)
                - Players take turns placing their marks
                - First to get 3 marks in a row (horizontal, vertical, or diagonal) wins
                - If all spaces are filled with no winner, the game is a draw

                YOUR RESPONSE:
                - Provide ONLY two numbers separated by a space (row column)
                - Example: "1 2" places your O in row 1, column 2
                - Choose only from the valid moves list provided to you

                STRATEGY TIPS:
                - Study the board carefully and make strategic moves
                - Block your opponent's potential winning moves
                - Create opportunities for multiple winning paths
                - Pay attention to the valid moves and avoid illegal moves"""),
            debug_mode=debug_mode,
        )

        return Team(
            name="Tic Tac Toe Team",
            mode="coordinate",
            model=referee_model,
            success_criteria="The game is completed with a win, loss, or draw",
            members=[player_x, player_o],
            instructions=[
                "You are the Tic Tac Toe game coordinator and referee.",
                "Your role is to coordinate between two player agents:",
                "1. Player X - Makes moves for X",
                "2. Player O - Makes moves for O",
                "",
                "When receiving a task:",
                "1. Check the 'current_player' in the context",
                "2. If the current player is 'Player X':",
                "   - Forward the request to Player X agent",
                "   - Return their move response directly",
                "3. If the current player is 'Player O':",
                "   - Forward the request to Player O agent",
                "   - Return their move response directly",
                "4. If no current_player is specified:",
                "   - This indicates a request for game state analysis",
                "   - Analyze the position yourself and respond with a JSON object:",
                "   {",
                "       'game_over': true/false,",
                "       'result': 'X_win'/'O_win'/'draw'/null,",
                "   }",
                "",
                "IMPORTANT:",
                "- The current_player will be provided in the context",
                "- Do not ask for the current player, it's already in the context",
                "- Forward the entire context to the player agents",
                "- Do not modify player agent responses",
                "- For analysis requests, provide detailed evaluation of the game state.",
            ],
            debug_mode=debug_mode,
            markdown=True,
            show_members_responses=True,
            enable_agentic_context=True,
            add_context=True,
        )

    except Exception as e:
        logger.error(f"Error initializing tic-tac-toe team: {str(e)}")
        raise
