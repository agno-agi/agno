"""♟️ Chess Team Battle

This example demonstrates how to build a sophisticated multi-agent chess game where different AI models
compete against each other. The system coordinates multiple specialized agents working together to play chess.

The Chess Team includes:
- White Player Agent: Strategizes and makes moves for white pieces
- Black Player Agent: Strategizes and makes moves for black pieces
- Game Master Agent: Coordinates gameplay and provides position analysis

Example Gameplay Flow:
- Game Master coordinates between White and Black agents
- Each agent analyzes the current position and legal moves
- Agents make strategic decisions based on chess principles
- python-chess validates all moves and maintains game state
- Game continues until checkmate, stalemate, or draw conditions

The Chess Team uses:
- Specialized agent roles for different game aspects
- Turn-based coordination for sequential gameplay
- Real-time move validation and board updates
- Strategic analysis and position evaluation

View the README for instructions on how to run the application.
"""

from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.team.team import Team
from agno.utils.streamlit import get_model_with_provider

db_url = "postgresql+psycopg://db_user:wc6%40YU8evhm1234@localhost:5433/ai"


def get_chess_team(
    white_model: str = "gpt-4o",
    black_model: str = "claude-4-sonnet",
    master_model: str = "gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Team:
    """Get a Chess Team with specialized player agents.

    Args:
        white_model: Model ID for the white player agent
        black_model: Model ID for the black player agent
        master_model: Model ID for the game master agent
        user_id: Optional user ID for session tracking
        session_id: Optional session ID for game continuity

    Returns:
        Team instance configured for chess gameplay
    """

    # Get model instances with correct provider auto-detection
    white_model_instance = get_model_with_provider(white_model)
    black_model_instance = get_model_with_provider(black_model)
    master_model_instance = get_model_with_provider(master_model)

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    # Create specialized chess agents
    white_player_agent = Agent(
        name="White Player",
        model=white_model_instance,
        db=db,
        id="white-chess-player",
        user_id=user_id,
        session_id=session_id,
        role="White Chess Strategist",
        instructions="""
            You are a chess strategist playing as WHITE pieces.
            
            Your responsibilities:
            1. Analyze the current board position and legal moves
            2. Apply chess principles: piece development, center control, king safety
            3. Consider tactical opportunities: pins, forks, skewers, discovered attacks
            4. Plan strategic goals: pawn structure, piece coordination, endgame preparation
            5. Choose the best move from the provided legal options
            
            Response format:
            - Respond ONLY with your chosen move in UCI notation (e.g., 'e2e4')
            - Do not include any explanation or additional text
            - Ensure your move is from the provided legal moves list
            
            Chess principles to follow:
            - Control the center (e4, d4, e5, d5 squares)
            - Develop pieces before moving them twice
            - Castle early for king safety
            - Don't bring queen out too early
            - Consider piece activity and coordination
        """,
        markdown=True,
        debug_mode=True,
    )

    black_player_agent = Agent(
        name="Black Player",
        model=black_model_instance,
        db=db,
        id="black-chess-player",
        user_id=user_id,
        session_id=session_id,
        role="Black Chess Strategist",
        instructions="""
            You are a chess strategist playing as BLACK pieces.
            
            Your responsibilities:
            1. Analyze the current board position and legal moves
            2. Apply chess principles: piece development, center control, king safety
            3. Consider tactical opportunities: pins, forks, skewers, discovered attacks  
            4. Plan strategic goals: pawn structure, piece coordination, endgame preparation
            5. Choose the best move from the provided legal options
            
            Response format:
            - Respond ONLY with your chosen move in UCI notation (e.g., 'e7e5')
            - Do not include any explanation or additional text
            - Ensure your move is from the provided legal moves list
            
            Chess principles to follow:
            - Control the center (e4, d4, e5, d5 squares)
            - Develop pieces before moving them twice
            - Castle early for king safety
            - Don't bring queen out too early
            - Consider piece activity and coordination
            - React to white's opening strategy appropriately
        """,
        markdown=True,
        debug_mode=True,
    )

    # Create the chess team with game master coordination
    chess_team = Team(
        name="Chess Team",
        model=master_model_instance,
        db=db,
        id="chess-game-team",
        user_id=user_id,
        session_id=session_id,
        members=[white_player_agent, black_player_agent],
        mode="route",
        instructions="""
            You are the Chess Game Master coordinating an AI vs AI chess match.
            
            Your roles:
            1. MOVE COORDINATION: Route move requests to the appropriate player agent
            2. GAME ANALYSIS: Provide position evaluation and commentary when requested
            3. GAME STATE: Monitor game progress and detect special conditions
            
            When handling requests:
            
            FOR MOVE REQUESTS:
            - Check 'current_player' in the context/dependencies
            - If current_player is 'white_piece_agent': route to White Player
            - If current_player is 'black_piece_agent': route to Black Player
            - Return the player's move response EXACTLY without modification
            
            FOR ANALYSIS REQUESTS:
            - When no current_player is specified, provide game analysis
            - Evaluate piece activity, king safety, material balance
            - Assess tactical and strategic themes in the position
            - Comment on recent moves and future planning
            
            Important guidelines:
            - Never modify or interpret player agent responses
            - Route move requests directly to the appropriate agent
            - Only provide analysis when explicitly requested
            - Maintain game flow and coordinate smooth turn transitions
        """,
        markdown=True,
        debug_mode=True,
        show_members_responses=True,
    )

    return chess_team
