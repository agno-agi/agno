import logging
from typing import Dict

import nest_asyncio
import streamlit as st
from agno.utils.log import logger
from chess_board import ChessBoard
from main import ChessGame

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

nest_asyncio.apply()

# Page configuration
st.set_page_config(
    page_title="Chess Team AI",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for styling
CUSTOM_CSS = """
<style>
.main-title {
    text-align: center;
    background: linear-gradient(45deg, #1a1a1a, #4a4a4a);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 3em;
    font-weight: bold;
    padding: 1em 0;
}
.subtitle {
    text-align: center;
    color: #666;
    margin-bottom: 2em;
}
.chess-board {
    font-family: 'Courier New', Courier, monospace;
    font-size: 1.5em;
    white-space: pre;
    background-color: #2b2b2b;
    padding: 20px;
    border-radius: 10px;
    margin: 20px 0;
    line-height: 1.2;
    letter-spacing: 0.1em;
    color: #fff;
}
.move-history {
    background-color: #2b2b2b;
    padding: 15px;
    border-radius: 10px;
    margin: 10px 0;
}
.agent-status {
    background-color: #1e1e1e;
    border-left: 4px solid #4CAF50;
    padding: 10px;
    margin: 10px 0;
    border-radius: 4px;
}
.agent-thinking {
    display: flex;
    align-items: center;
    background-color: #2b2b2b;
    padding: 10px;
    border-radius: 5px;
    margin: 10px 0;
    border-left: 4px solid #FFA500;
}
.piece-moving {
    background-color: #1e1e1e;
    border-left: 4px solid #FFA500;
    padding: 15px;
    margin: 10px 0;
    border-radius: 4px;
    font-size: 1.2em;
    animation: highlight 2s ease-in-out;
}
@keyframes highlight {
    0% { background-color: #2d4f1e; }
    50% { background-color: #1e1e1e; }
    100% { background-color: #2d4f1e; }
}
.last-move {
    color: #4CAF50;
    font-weight: bold;
}
.chess-board-wrapper {
    font-family: 'Courier New', monospace;
    background: #2b2b2b;
    padding: 20px;
    border-radius: 10px;
    display: inline-block;
    margin: 20px auto;
    text-align: center;
}
.board-container {
    display: flex;
    justify-content: center;
    width: 100%;
}
.chess-files {
    color: #888;
    text-align: center;
    padding: 5px 0;
    margin-left: 30px;
    display: flex;
    justify-content: space-around;
    width: calc(100% - 30px);
    margin-bottom: 5px;
}
.chess-file-label {
    width: 40px;
    text-align: center;
}
.chess-grid {
    border: 1px solid #666;
    display: inline-block;
}
.chess-row {
    display: flex;
    align-items: center;
}
.chess-rank {
    color: #888;
    width: 25px;
    text-align: center;
    padding-right: 5px;
}
.chess-cell {
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid #666;
    font-size: 24px;
}
.piece-white {
    color: #fff;
}
.piece-black {
    color: #aaa;
}
.piece-empty {
    color: transparent;
}
.chess-row:nth-child(odd) .chess-cell:nth-child(even),
.chess-row:nth-child(even) .chess-cell:nth-child(odd) {
    background-color: #3c3c3c;
}
.chess-row:nth-child(even) .chess-cell:nth-child(even),
.chess-row:nth-child(odd) .chess-cell:nth-child(odd) {
    background-color: #262626;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def display_board(board: ChessBoard):
    """Display the chess board in a formatted way"""
    st.markdown('<div class="board-container">', unsafe_allow_html=True)
    st.markdown(board.get_board_state(), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def add_move_to_history(move: str, player: str, piece_info: Dict[str, str] = None):
    """Add a move to the game history with piece information"""
    if "move_history" not in st.session_state:
        st.session_state.move_history = []

    move_number = len(st.session_state.move_history) + 1
    st.session_state.move_history.append(
        {
            "number": move_number,
            "player": player,
            "move": move,
            "piece": piece_info.get("piece_name", "") if piece_info else "",
        }
    )


def display_move_history():
    """Display the move history in a formatted way"""
    if "move_history" in st.session_state and st.session_state.move_history:
        st.sidebar.markdown("### Move History")

        piece_symbols = {
            "King": ("♔", "♚"),
            "Queen": ("♕", "♛"),
            "Rook": ("♖", "♜"),
            "Bishop": ("♗", "♝"),
            "Knight": ("♘", "♞"),
            "Pawn": ("♙", "♟"),
        }

        # Create a formatted move history
        moves_text = []
        current_move = {
            "number": 1,
            "white": "",
            "white_piece": "",
            "black": "",
            "black_piece": "",
        }

        for move in st.session_state.move_history:
            if move["player"] == "White":
                if current_move["white"]:
                    moves_text.append(current_move)
                    current_move = {
                        "number": len(moves_text) + 1,
                        "white": "",
                        "white_piece": "",
                        "black": "",
                        "black_piece": "",
                    }
                current_move["white"] = move["move"]
                piece_name = move.get("piece", "")
                if piece_name in piece_symbols:
                    current_move["white_piece"] = piece_symbols[piece_name][
                        0
                    ]  # White piece symbol
            else:
                current_move["black"] = move["move"]
                piece_name = move.get("piece", "")
                if piece_name in piece_symbols:
                    current_move["black_piece"] = piece_symbols[piece_name][
                        1
                    ]  # Black piece symbol
                moves_text.append(current_move)
                current_move = {
                    "number": len(moves_text) + 1,
                    "white": "",
                    "white_piece": "",
                    "black": "",
                    "black_piece": "",
                }

        if current_move["white"] or current_move["black"]:
            moves_text.append(current_move)

        # Display moves in a table format
        history_text = "Move │ White       │ Black\n"
        history_text += "─────┼────────────┼────────────\n"

        for move in moves_text:
            white = (
                f"{move['white_piece']} {move['white']}"
                if move["white_piece"]
                else move["white"]
            )
            black = (
                f"{move['black_piece']} {move['black']}"
                if move["black_piece"]
                else move["black"]
            )
            history_text += f"{move['number']:3d}. │ {white:10s} │ {black:10s}\n"

        st.sidebar.markdown(f"```\n{history_text}\n```")


def show_agent_status(agent_name: str, status: str):
    """Display the current agent status"""
    st.markdown(
        f"""<div class="agent-status">
            🤖 <b>{agent_name}</b>: {status}
        </div>""",
        unsafe_allow_html=True,
    )


def show_thinking_indicator(agent_name: str):
    """Show a thinking indicator for the current agent"""
    with st.container():
        st.markdown(
            f"""<div class="agent-thinking">
                <div style="margin-right: 10px;">🔄</div>
                <div>{agent_name} is thinking...</div>
            </div>""",
            unsafe_allow_html=True,
        )


def extract_move_from_response(response: str) -> str:
    """Extract chess move from AI response"""
    try:
        # Look for moves in format like e2e4
        import re

        move_pattern = r"[a-h][1-8][a-h][1-8]"
        moves = re.findall(move_pattern, str(response))

        if moves:
            return moves[0]

        # Fallback: look for moves in quoted text
        quoted_pattern = r'"([a-h][1-8][a-h][1-8])"'
        quoted_moves = re.findall(quoted_pattern, str(response))
        if quoted_moves:
            return quoted_moves[0]

        return None
    except Exception as e:
        st.error(f"Error extracting move: {str(e)}")
        return None


def display_game_status():
    """Display the current game status"""
    if "game_started" in st.session_state and st.session_state.game_started:
        st.sidebar.markdown("### Game Status")

        # Show active agents
        st.sidebar.markdown("**Active Agents:**")
        agents = {
            "White Piece Agent": "Waiting for next move"
            if len(st.session_state.move_history) % 2 == 0
            else "Thinking...",
            "Black Piece Agent": "Thinking..."
            if len(st.session_state.move_history) % 2 == 1
            else "Waiting for next move",
            "Legal Move Agent": "Ready to validate",
            "Master Agent": "Monitoring game",
        }

        for agent, status in agents.items():
            st.sidebar.markdown(
                f"""<div class="agent-status" style="font-size: 0.9em;">
                    🤖 {agent}<br/>
                    <small style="color: #888;">{status}</small>
                </div>""",
                unsafe_allow_html=True,
            )

        # Show current turn
        current_turn = (
            "White" if len(st.session_state.move_history) % 2 == 0 else "Black"
        )
        st.sidebar.markdown(f"**Current Turn:** {current_turn}")


def check_game_ending_conditions(
    board_state: str, legal_moves: str, current_color: str
) -> bool:
    """Check if the game has ended (checkmate/stalemate/draw)"""
    try:
        show_agent_status("Master Agent", "Analyzing position...")
        with st.spinner("🔍 Checking game status..."):
            analysis_prompt = f"""Current board state:
{board_state}

Current player: {current_color}
Legal moves available: {legal_moves}

Analyze this position and determine if the game has ended.
Consider:
1. Is this checkmate? (king in check with no legal moves)
2. Is this stalemate? (no legal moves but king not in check)
3. Is this a draw? (insufficient material or repetition)

Respond with appropriate status."""

            master_response = st.session_state.game.agents["master"].run(
                analysis_prompt, stream=False
            )

            response_content = (
                master_response.content.strip() if master_response else ""
            )
            logger.debug(f"Master analysis: {response_content}")

            if "CHECKMATE" in response_content.upper():
                st.success(f"🏆 {response_content}")
                return True
            elif "STALEMATE" in response_content.upper():
                st.info("🤝 Game ended in stalemate!")
                return True
            elif "DRAW" in response_content.upper():
                st.info(f"🤝 {response_content}")
                return True

            return False

    except Exception as e:
        logger.error(f"Error checking game end: {str(e)}")
        return False


def format_move_description(move_info: Dict[str, str], player: str) -> str:
    """Format a nice description of the move with Unicode pieces"""
    piece_symbols = {
        "King": "♔" if player == "White" else "♚",
        "Queen": "♕" if player == "White" else "♛",
        "Rook": "♖" if player == "White" else "♜",
        "Bishop": "♗" if player == "White" else "♝",
        "Knight": "♘" if player == "White" else "♞",
        "Pawn": "♙" if player == "White" else "♟",
    }

    if all(key in move_info for key in ["piece_name", "from", "to"]):
        piece_symbol = piece_symbols.get(move_info["piece_name"], "")
        return f"{player}'s {piece_symbol} {move_info['piece_name']} moves {move_info['from']} → {move_info['to']}"
    return f"{player} moves {move_info.get('from', '')} → {move_info.get('to', '')}"


def play_next_move(retry_count: int = 0, max_retries: int = 3):
    """Have the AI agents play the next move"""
    if retry_count >= max_retries:
        st.error(f"Failed to make a valid move after {max_retries} attempts")
        return False

    try:
        # Get the board object instead of just the state
        current_board = st.session_state.game.board
        board_state = current_board.get_board_state()

        # Determine whose turn it is
        is_white_turn = len(st.session_state.move_history) % 2 == 0
        current_agent = "white" if is_white_turn else "black"
        agent_name = "White Piece Agent" if is_white_turn else "Black Piece Agent"
        current_color = "white" if is_white_turn else "black"

        # First, get legal moves from legal move agent
        show_agent_status("Legal Move Agent", "Calculating legal moves...")
        try:
            with st.spinner("🎲 Calculating legal moves..."):
                legal_prompt = f"""Current board state:
{board_state}

List ALL legal moves for {current_color} pieces. Return as comma-separated list."""

                legal_response = st.session_state.game.agents["legal"].run(
                    legal_prompt, stream=False
                )

                legal_moves = legal_response.content.strip() if legal_response else ""
                logger.debug(f"Legal moves: {legal_moves}")

                if not legal_moves:
                    # If no legal moves, check if it's checkmate or stalemate
                    if check_game_ending_conditions(
                        board_state, legal_moves, current_color
                    ):
                        st.session_state.game_paused = True  # Pause the game
                        return False
                    return False

        except Exception as e:
            logger.error(f"Error getting legal moves: {str(e)}")
            st.error("Error calculating legal moves")
            return False

        # Now, have the piece agent choose from legal moves
        show_agent_status(agent_name, "Choosing best move...")
        try:
            with st.spinner(f"🤔 {agent_name} is thinking..."):
                choice_prompt = f"""Current board state:
{board_state}

Legal moves available: {legal_moves}

Choose the best move from these legal moves. Respond ONLY with your chosen move."""

                agent_response = st.session_state.game.agents[current_agent].run(
                    choice_prompt, stream=False
                )

                # Extract move from response content
                response_content = agent_response.content if agent_response else None
                logger.debug(f"Agent choice: {response_content}")

                if response_content:
                    ai_move = response_content.strip()

                    # Verify the chosen move is in the legal moves list
                    legal_moves_list = legal_moves.replace(" ", "").split(",")
                    if ai_move not in legal_moves_list:
                        logger.error(
                            f"Chosen move {ai_move} not in legal moves! Available moves: {legal_moves_list}"
                        )
                        st.warning(
                            f"Invalid move choice by {agent_name}, retrying... (Attempt {retry_count + 1}/{max_retries})"
                        )
                        return play_next_move(retry_count + 1, max_retries)

                    # Make the move
                    result = st.session_state.game.make_move(ai_move)
                    if "successful" in result.get("status", ""):
                        # Add move to history with piece information
                        add_move_to_history(
                            ai_move, "White" if is_white_turn else "Black", result
                        )

                        # Show piece movement with description
                        move_description = format_move_description(
                            result, "White" if is_white_turn else "Black"
                        )

                        st.markdown(
                            f"""<div class="piece-moving">
                                🎯 {move_description}
                            </div>""",
                            unsafe_allow_html=True,
                        )

                        # Force a rerun to update the board
                        st.rerun()
                        return True
                    else:
                        logger.error(f"Move failed: {result}")
                        st.warning(
                            f"Invalid move by {agent_name}, retrying... (Attempt {retry_count + 1}/{max_retries})"
                        )
                        return play_next_move(retry_count + 1, max_retries)
                else:
                    logger.error("No response content from agent")
                    st.warning(
                        f"No response from {agent_name}, retrying... (Attempt {retry_count + 1}/{max_retries})"
                    )
                    return play_next_move(retry_count + 1, max_retries)

        except Exception as e:
            logger.error(f"Error during agent move: {str(e)}")
            st.warning(
                f"Error during {agent_name}'s move, retrying... (Attempt {retry_count + 1}/{max_retries})"
            )
            return play_next_move(retry_count + 1, max_retries)

    except Exception as e:
        logger.error(f"Unexpected error in play_next_move: {str(e)}")
        st.error(f"Error during game play: {str(e)}")
        return False


def main():
    st.markdown("<h1 class='main-title'>Chess Team AI</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Watch AI agents play chess against each other!</p>",
        unsafe_allow_html=True,
    )

    # Initialize session state
    if "game_started" not in st.session_state:
        st.session_state.game_started = False
        st.session_state.game_paused = False

    # Sidebar
    with st.sidebar:
        st.markdown("### Game Controls")

        col1, col2 = st.columns(2)

        # Start/Pause Game button
        with col1:
            if not st.session_state.game_started:
                if st.button("▶️ Start Game"):
                    st.session_state.game = ChessGame()
                    st.session_state.game_started = True
                    st.session_state.move_history = []
                    st.rerun()
            else:
                if st.button(
                    "⏸️ Pause" if not st.session_state.game_paused else "▶️ Resume"
                ):
                    st.session_state.game_paused = not st.session_state.game_paused
                    st.rerun()

        # New Game button
        with col2:
            if st.session_state.game_started:
                if st.button("🔄 New Game"):
                    st.session_state.game = ChessGame()
                    st.session_state.move_history = []
                    st.rerun()

        st.markdown("### About")
        st.markdown("""
        Watch two AI agents play chess:
        - White Piece Agent vs Black Piece Agent
        - Legal Move Agent validates moves
        - Master Agent coordinates the game
        """)

    # Main game area
    if st.session_state.game_started:
        # Create columns for board and move history
        col1, col2 = st.columns([2, 1])

        with col1:
            # Display current board - pass the board object instead of just the state
            display_board(st.session_state.game.board)

            # Auto-play next move if game is not paused
            if not st.session_state.game_paused:
                if play_next_move():
                    st.rerun()  # Refresh to show the new state

        with col2:
            display_move_history()
    else:
        # Display welcome message when game hasn't started
        st.info("👈 Click 'Start Game' in the sidebar to begin!")

    # Display game status
    display_game_status()


if __name__ == "__main__":
    main()
