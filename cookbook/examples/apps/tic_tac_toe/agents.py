"""
Tic Tac Toe Battle
---------------------------------
This example shows how to build a Tic Tac Toe game where two AI agents play against each other.
The game features a referee agent coordinating between two player agents using different
language models.

Usage Examples:
---------------
1. Quick game with default settings:
   referee_agent = get_tic_tac_toe_referee()
   play_tic_tac_toe()

2. Game with debug mode off:
   referee_agent = get_tic_tac_toe_referee(debug_mode=False)
   play_tic_tac_toe(debug_mode=False)

The game integrates:
  - Multiple AI models (Claude, GPT-4, etc.)
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
        return Claude(id=model_name)
    elif provider == "groq":
        return Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")


def get_tic_tac_toe_referee(
    model_x: str = "openai:gpt-4o",
    model_o: str = "openai:o3-mini",
    model_referee: str = "openai:gpt-4o",
    debug_mode: bool = True,
) -> Agent:
    """
    Returns an instance of the Tic Tac Toe Referee Agent that coordinates the game.

    Args:
        model_x: ModelConfig for player X
        model_o: ModelConfig for player O
        model_referee: ModelConfig for the referee agent
        debug_mode: Enable logging and debug features

    Returns:
        An instance of the configured Referee Agent
    """
    # Parse model provider and name
    provider_x, model_name_x = model_x.split(":")
    provider_o, model_name_o = model_o.split(":")
    provider_referee, model_name_referee = model_referee.split(":")

    # Create model instances using the helper function
    model_x = get_model_for_provider(provider_x, model_name_x)
    model_o = get_model_for_provider(provider_o, model_name_o)
    model_referee = get_model_for_provider(provider_referee, model_name_referee)

    player1 = Agent(
        name="Player 1",
        description=dedent("""\
        You are the X player in Tic Tac Toe. Your goal is to win by placing three X's in a row (horizontally, vertically, or diagonally).

        Game Rules:
        - You must make valid moves on a 3x3 grid using row (0-2) and column (0-2) coordinates
        - The top-left corner is (0,0), and bottom-right is (2,2)
        - You can only place X's in empty spaces marked by " " on the board
        - You will be given a list of valid moves - only choose from these moves
        - Respond with ONLY the row and column numbers for your move, e.g. "1 2"

        Strategy:
        - Study the board carefully and make strategic moves
        - Try to create winning opportunities while blocking your opponent
        - Pay attention to the valid moves list to avoid illegal moves
        """),
        model=model_x,
    )

    player2 = Agent(
        name="Player 2",
        description=dedent("""\
        You are the O player in Tic Tac Toe. Your goal is to win by placing three O's in a row (horizontally, vertically, or diagonally).

        Game Rules:
        - You must make valid moves on a 3x3 grid using row (0-2) and column (0-2) coordinates
        - The top-left corner is (0,0), and bottom-right is (2,2)
        - You can only place O's in empty spaces marked by " " on the board
        - You will be given a list of valid moves - only choose from these moves
        - Respond with ONLY the row and column numbers for your move, e.g. "1 2"

        Strategy:
        - Study the board carefully and make strategic moves to win
        - Block your opponent's winning opportunities
        - Pay attention to the valid moves list to avoid illegal moves
        """),
        model=model_o,
    )

    t3_agent = Agent(
        name="Tic Tac Toe Referee Agent",
        description=dedent("""\
        You are the referee of a Tic Tac Toe game. Your responsibilities include:

        Game Management:
        1. Track and maintain the current board state
        2. Validate all moves before they are made
        3. Ensure moves are only made in empty spaces (marked by " ")
        4. Keep track of whose turn it is (X goes first)

        Move Validation:
        1. Check that moves are within the 3x3 grid (0-2 for rows and columns)
        2. Verify the chosen position is empty before allowing a move
        3. Maintain and provide the list of valid moves to players

        Game State Checking:
        1. Check for winning conditions after each move:
           - Three X's or O's in a row horizontally
           - Three X's or O's in a row vertically
           - Three X's or O's in a row diagonally
        2. Check for draw conditions:
           - Board is full with no winner

        Communication:
        1. Announce the current state of the board after each move
        2. Declare moves as valid or invalid
        3. Announce the winner or draw when game ends
        4. Provide clear feedback to players about their moves

        You will coordinate between the X and O players, ensuring fair play and proper game progression.
        """),
        model=model_referee,
        team=[player1, player2],
        show_tool_calls=True,
        markdown=True,
        debug_mode=debug_mode,
    )

    return t3_agent
