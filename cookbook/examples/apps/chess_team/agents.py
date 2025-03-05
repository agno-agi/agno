"""
Chess Team Battle
---------------------------------
This example shows how to build a Chess game where AI agents play different roles in a team.
The game features specialized agents for strategy for white pieces, strategy for black pieces,
and a master agent overseeing the game. Move validation is handled by python-chess.

Usage Examples:
---------------
1. Quick game with default settings:
   agents = get_chess_teams()

2. Game with debug mode off:
   agents = get_chess_teams(debug_mode=False)

The game integrates:
  - Multiple AI models (Claude, GPT-4, etc.)
  - Specialized agent roles (strategist, master)
  - Turn-based gameplay coordination
  - Move validation using python-chess
"""

import sys
from pathlib import Path
from typing import Dict

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
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
            )
        else:
            return Claude(id=model_name)
    elif provider == "groq":
        return Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")


def get_chess_teams(
    white_model: str = "openai:gpt-4o",
    black_model: str = "anthropic:claude-3-7-sonnet",
    master_model: str = "openai:gpt-4o",
    debug_mode: bool = True,
) -> Dict[str, Agent]:
    """
    Returns a dictionary of chess agents with specific roles.

    Args:
        white_model: Model for white piece strategy
        black_model: Model for black piece strategy
        master_model: Model for game state evaluation
        debug_mode: Enable logging and debug features

    Returns:
        Dictionary of configured agents
    """
    try:
        # Parse model providers and names
        white_provider, white_name = white_model.split(":")
        black_provider, black_name = black_model.split(":")
        master_provider, master_name = master_model.split(":")

        # Create model instances
        white_piece_model = get_model_for_provider(white_provider, white_name)
        black_piece_model = get_model_for_provider(black_provider, black_name)
        master_model = get_model_for_provider(master_provider, master_name)

        # Create agents
        white_piece_agent = Agent(
            name="white_piece_agent",
            description="""You are a chess strategist for white pieces. Given a list of legal moves,
                    analyze them and choose the best one based on standard chess strategy.
                    Consider piece development, center control, and king safety.
                    Respond ONLY with your chosen move in UCI notation (e.g., 'e2e4').""",
            model=white_piece_model,
            debug_mode=debug_mode,
        )

        black_piece_agent = Agent(
            name="black_piece_agent",
            description="""You are a chess strategist for black pieces. Given a list of legal moves,
                    analyze them and choose the best one based on standard chess strategy.
                    Consider piece development, center control, and king safety.
                    Respond ONLY with your chosen move in UCI notation (e.g., 'e7e5').""",
            model=black_piece_model,
            debug_mode=debug_mode,
        )

        master_agent = Agent(
            name="master_agent",
            description="""You are a chess master overseeing the game. Your responsibilities:
                    1. Analyze the current board state to determine if the game has ended
                    2. Check for checkmate, stalemate, draw by repetition, or insufficient material
                    3. Provide commentary on the current state of the game
                    4. Evaluate the position and suggest who has an advantage
                    
                    Respond with a JSON object containing:
                    {
                        "game_over": true/false,
                        "result": "white_win"/"black_win"/"draw"/null,
                        "reason": "explanation if game is over",
                        "commentary": "brief analysis of the position",
                        "advantage": "white"/"black"/"equal"
                    }""",
            model=master_model,
            debug_mode=debug_mode,
        )

        return {
            "white_piece_agent": white_piece_agent,
            "black_piece_agent": black_piece_agent,
            "master_agent": master_agent,
        }
    except Exception as e:
        logger.error(f"Error initializing agents: {str(e)}")
        raise
