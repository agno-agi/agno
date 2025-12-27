import re
from typing import Dict, List

import chess
import nest_asyncio
import streamlit as st
from agents import get_chess_team
from agno.utils.streamlit import (
    COMMON_CSS,
    about_section,
    add_message,
    display_chat_messages,
    display_response,
    export_chat_history,
    initialize_agent,
    reset_session_state,
    session_selector_widget,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="Chess Team Battle",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)

# Chess-specific CSS additions
st.markdown(
    """
<style>
    .chess-board {
        width: 100%;
        max-width: 500px;
        margin: 0 auto;
        border: 2px solid #555;
        border-radius: 5px;
        overflow: hidden;
    }
    
    .chess-square {
        width: 12.5%;
        aspect-ratio: 1;
        display: inline-block;
        text-align: center;
        font-size: 24px;
        line-height: 60px;
        vertical-align: middle;
    }
    
    .white-square {
        background-color: #f0d9b5;
        color: #000;
    }
    
    .black-square {
        background-color: #b58863;
        color: #000;
    }
    
    .piece {
        font-size: 32px;
        line-height: 60px;
    }
    
    .game-status {
        text-align: center;
        padding: 10px;
        margin: 10px 0;
        border-radius: 5px;
        background-color: rgba(100, 100, 100, 0.2);
    }
    
    .player-turn {
        background-color: rgba(70, 130, 180, 0.3);
        border-left: 4px solid #4682B4;
    }
    
    .game-over {
        background-color: rgba(50, 205, 50, 0.3);
        border-left: 4px solid #32CD32;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Chess board constants
WHITE = "white"
BLACK = "black"

PIECE_SYMBOLS = {
    "r": "♜",
    "n": "♞",
    "b": "♝",
    "q": "♛",
    "k": "♚",
    "p": "♟",
    "R": "♖",
    "N": "♘",
    "B": "♗",
    "Q": "♕",
    "K": "♔",
    "P": "♙",
}

MODELS = [
    "gpt-4o",
    "o3-mini",
    "claude-sonnet-4-20250514",
    "claude-opus-4-1-20250805",
]


class ChessBoard:
    """Chess board wrapper for python-chess."""

    def __init__(self):
        self.board = chess.Board()

    def get_fen(self) -> str:
        """Get FEN string representation."""
        return self.board.fen

    def get_board_state(self) -> str:
        """Get text representation of the board."""
        return str(self.board)

    @property
    def current_color(self) -> str:
        """Get current player color."""
        return WHITE if self.board.turn else BLACK

    def make_move(self, move_str: str) -> tuple[bool, str]:
        """Make a move on the board."""
        try:
            move = chess.Move.from_uci(move_str)
            if move in self.board.legal_moves:
                self.board.push(move)
                return True, f"Move {move_str} played successfully"
            else:
                return False, f"Illegal move: {move_str}"
        except Exception as e:
            return False, f"Invalid move format: {str(e)}"

    def get_game_state(self) -> tuple[bool, Dict]:
        """Check if game is over and return state info."""
        if self.board.is_checkmate():
            winner = BLACK if self.board.turn else WHITE
            return True, {"result": f"{winner}_win", "reason": "checkmate"}
        elif self.board.is_stalemate():
            return True, {"result": "draw", "reason": "stalemate"}
        elif self.board.is_insufficient_material():
            return True, {"result": "draw", "reason": "insufficient material"}
        elif self.board.is_seventyfive_moves():
            return True, {"result": "draw", "reason": "75-move rule"}
        elif self.board.is_fivefold_repetition():
            return True, {"result": "draw", "reason": "fivefold repetition"}
        else:
            return False, {}

    def get_legal_moves_with_descriptions(self) -> List[Dict]:
        """Get all legal moves with descriptions."""
        legal_moves = []

        for move in self.board.legal_moves:
            from_square = chess.square_name(move.from_square)
            to_square = chess.square_name(move.to_square)

            piece = self.board.piece_at(move.from_square)
            piece_type = piece.symbol().upper() if piece else "?"

            is_capture = self.board.is_capture(move)

            # Check for special moves
            if self.board.is_kingside_castling(move):
                description = "Kingside castle (O-O)"
            elif self.board.is_queenside_castling(move):
                description = "Queenside castle (O-O-O)"
            elif move.promotion:
                promotion = chess.piece_name(move.promotion)
                description = (
                    f"Pawn {from_square} to {to_square}, promote to {promotion}"
                )
            elif is_capture:
                captured_piece = self.board.piece_at(move.to_square)
                captured_type = (
                    captured_piece.symbol().upper() if captured_piece else "?"
                )
                description = f"{piece_type} from {from_square} captures {captured_type} at {to_square}"
            else:
                description = f"{piece_type} from {from_square} to {to_square}"

            legal_moves.append(
                {
                    "uci": move.uci(),
                    "san": self.board.san(move),
                    "description": description,
                    "is_capture": is_capture,
                }
            )

        return legal_moves


def display_board(chess_board: ChessBoard):
    """Display the chess board."""
    st.markdown('<div class="chess-board">', unsafe_allow_html=True)

    # Board layout (8x8 grid)
    for rank in range(8, 0, -1):  # 8 to 1
        row_html = ""
        for file in range(8):  # a to h
            square = chess.square(file, rank - 1)
            piece = chess_board.board.piece_at(square)

            # Determine square color
            is_light = (rank + file) % 2 == 1
            square_class = "white-square" if is_light else "black-square"

            # Get piece symbol
            piece_symbol = ""
            if piece:
                piece_symbol = PIECE_SYMBOLS.get(piece.symbol(), piece.symbol())

            row_html += f'<div class="chess-square {square_class}"><span class="piece">{piece_symbol}</span></div>'

        st.markdown(row_html, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def parse_move(response_text: str) -> str:
    """Extract move from agent response."""
    if not response_text:
        return ""

    response_text = response_text.strip()

    if (
        len(response_text) >= 4
        and response_text[0] in "abcdefgh"
        and response_text[1] in "12345678"
        and response_text[2] in "abcdefgh"
        and response_text[3] in "12345678"
    ):
        return response_text

    uci_match = re.search(r"([a-h][1-8][a-h][1-8][qrbn]?)", response_text)
    if uci_match:
        return uci_match.group(1)

    return response_text


def find_move_from_san(san_move: str, legal_moves: List[Dict]) -> str:
    """Convert SAN notation to UCI by finding it in legal moves."""
    san_move = san_move.strip()

    for move in legal_moves:
        if move["san"] == san_move:
            return move["uci"]

    return ""


def restart_chess_game(
    white_model: str = None, black_model: str = None, master_model: str = None
):
    """Restart the chess game with new settings."""
    white_model = white_model or st.session_state.get("white_model", MODELS[0])
    black_model = black_model or st.session_state.get("black_model", MODELS[1])
    master_model = master_model or st.session_state.get("master_model", MODELS[0])

    new_team = get_chess_team(
        white_model=white_model,
        black_model=black_model,
        master_model=master_model,
        session_id=None,
    )

    st.session_state["agent"] = new_team
    st.session_state["session_id"] = new_team.session_id
    st.session_state["white_model"] = white_model
    st.session_state["black_model"] = black_model
    st.session_state["master_model"] = master_model
    st.session_state["chess_board"] = ChessBoard()
    st.session_state["game_started"] = True
    st.session_state["game_paused"] = False
    st.session_state["move_history"] = []
    st.session_state["is_new_session"] = True


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Chess Team Battle</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Watch AI agents compete in strategic chess matches</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selectors
    ####################################################################
    st.sidebar.markdown("#### ♔ White Player")
    selected_white = st.sidebar.selectbox(
        "Select White Player Model",
        options=MODELS,
        index=0,
        key="white_selector",
    )

    st.sidebar.markdown("#### ♚ Black Player")
    selected_black = st.sidebar.selectbox(
        "Select Black Player Model",
        options=MODELS,
        index=1 if len(MODELS) > 1 else 0,
        key="black_selector",
    )

    st.sidebar.markdown("#### 🧠 Game Master")
    selected_master = st.sidebar.selectbox(
        "Select Game Master Model",
        options=MODELS,
        index=0,
        key="master_selector",
    )

    ####################################################################
    # Initialize Chess Team and Session
    ####################################################################
    if "game_started" not in st.session_state:
        st.session_state.game_started = False

    if st.session_state.game_started:
        chess_team = initialize_agent(
            selected_white,
            lambda model_id, session_id: get_chess_team(
                white_model=selected_white,
                black_model=selected_black,
                master_model=selected_master,
                session_id=session_id,
            ),
        )
        reset_session_state(chess_team)

    ####################################################################
    # Game Controls
    ####################################################################
    st.sidebar.markdown("#### 🎮 Game Controls")

    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if not st.session_state.game_started:
            if st.sidebar.button("▶️ Start Game", use_container_width=True):
                restart_chess_game(selected_white, selected_black, selected_master)
                st.rerun()
        else:
            game_over = False
            if "chess_board" in st.session_state:
                game_over, _ = st.session_state.chess_board.get_game_state()

            if not game_over:
                if st.sidebar.button(
                    "⏸️ Pause"
                    if not st.session_state.get("game_paused", False)
                    else "▶️ Resume",
                    use_container_width=True,
                ):
                    st.session_state.game_paused = not st.session_state.get(
                        "game_paused", False
                    )
                    st.rerun()

    with col2:
        if st.session_state.game_started:
            if st.sidebar.button("🔄 New Game", use_container_width=True):
                restart_chess_game(selected_white, selected_black, selected_master)
                st.rerun()

    ####################################################################
    # Sample Actions
    ####################################################################
    if st.session_state.game_started:
        st.sidebar.markdown("#### 🎯 Quick Actions")
        if st.sidebar.button("📊 Analyze Position"):
            if "chess_board" in st.session_state:
                fen = st.session_state.chess_board.get_fen()
                board_state = st.session_state.chess_board.get_board_state()

                analysis_prompt = f"""
                Analyze this chess position:
                
                FEN: {fen}
                Board:
                {board_state}
                
                Provide analysis of:
                - Material balance
                - Piece activity
                - King safety
                - Tactical themes
                - Strategic assessment
                """
                add_message("user", analysis_prompt)

        if st.sidebar.button("📈 Game Summary"):
            if st.session_state.get("move_history", []):
                moves = st.session_state.move_history
                summary_prompt = f"""
                Provide a summary of this chess game:
                
                Total moves: {len(moves)}
                Recent moves: {", ".join([m["move"] for m in moves[-5:]])}
                
                Please analyze:
                - Opening played
                - Key turning points
                - Current position assessment
                - Game progression
                """
                add_message("user", summary_prompt)

    ####################################################################
    # Utility buttons
    ####################################################################
    if st.session_state.game_started:
        st.sidebar.markdown("#### 🛠️ Utilities")
        col1, col2 = st.sidebar.columns([1, 1])

        with col1:
            if st.sidebar.button("🔄 New Chat", use_container_width=True):
                restart_chess_game(selected_white, selected_black, selected_master)
                st.rerun()

        with col2:
            has_moves = (
                st.session_state.get("move_history")
                and len(st.session_state.move_history) > 0
            )

            if has_moves:
                session_id = st.session_state.get("session_id")
                filename = f"chess_game_{session_id or 'new'}.md"

                if st.sidebar.download_button(
                    "💾 Export Game",
                    export_chat_history("Chess Team Battle"),
                    file_name=filename,
                    mime="text/markdown",
                    use_container_width=True,
                    help=f"Export game with {len(st.session_state.move_history)} moves",
                ):
                    st.sidebar.success("Game exported!")
            else:
                st.sidebar.button(
                    "💾 Export Game",
                    disabled=True,
                    use_container_width=True,
                    help="No moves to export",
                )

    ####################################################################
    # Display Chat Messages
    ####################################################################
    if st.session_state.game_started:
        display_chat_messages()

        # Generate response for user message
        last_message = (
            st.session_state["messages"][-1]
            if st.session_state.get("messages")
            else None
        )
        if last_message and last_message.get("role") == "user":
            question = last_message["content"]
            display_response(st.session_state.agent, question)

    ####################################################################
    # Session management
    ####################################################################
    if st.session_state.game_started:
        session_selector_widget(
            st.session_state.agent,
            selected_white,
            lambda model_id, session_id: get_chess_team(
                white_model=selected_white,
                black_model=selected_black,
                master_model=selected_master,
                session_id=session_id,
            ),
        )

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Chess Team Battle showcases AI agents competing in strategic chess matches. Watch different models play against each other with real-time move analysis and game coordination."
    )

    ####################################################################
    # Main Game Display
    ####################################################################
    if st.session_state.game_started and "chess_board" in st.session_state:
        chess_board = st.session_state.chess_board
        game_over, state_info = chess_board.get_game_state()

        # Display current match-up
        st.markdown(
            f"<h3 style='text-align:center; color:#87CEEB;'>{selected_white} vs {selected_black}</h3>",
            unsafe_allow_html=True,
        )

        # Display chess board
        display_board(chess_board)

        # Game status
        if game_over:
            result = state_info.get("result", "")
            reason = state_info.get("reason", "")

            if "white_win" in result:
                st.markdown(
                    f'<div class="game-status game-over">🏆 Game Over! White ({selected_white}) wins by {reason}!</div>',
                    unsafe_allow_html=True,
                )
            elif "black_win" in result:
                st.markdown(
                    f'<div class="game-status game-over">🏆 Game Over! Black ({selected_black}) wins by {reason}!</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="game-status game-over">🤝 Game Over! Draw by {reason}!</div>',
                    unsafe_allow_html=True,
                )
        else:
            current_color = chess_board.current_color
            current_model = selected_white if current_color == WHITE else selected_black
            st.markdown(
                f'<div class="game-status player-turn">🎯 {current_color.capitalize()} to move ({current_model})</div>',
                unsafe_allow_html=True,
            )

        # Move history
        if st.session_state.get("move_history", []):
            with st.expander("📜 Move History", expanded=False):
                for move in st.session_state.move_history[-10:]:  # Show last 10 moves
                    st.write(
                        f"**{move['number']}.** {move['player']}: {move['move']} - {move['description']}"
                    )

        # Auto-play logic
        if not st.session_state.get("game_paused", False) and not game_over:
            current_color = chess_board.current_color
            current_agent_name = (
                "white_piece_agent" if current_color == WHITE else "black_piece_agent"
            )

            with st.spinner(f"🤔 {current_color.capitalize()} player thinking..."):
                # Get legal moves
                legal_moves = chess_board.get_legal_moves_with_descriptions()
                legal_moves_text = "\n".join(
                    [
                        f"- {move['san']} ({move['uci']}): {move['description']}"
                        for move in legal_moves
                    ]
                )

                # Create move request
                fen = chess_board.get_fen()
                board_state = chess_board.get_board_state()

                move_request = f"""Current board state (FEN): {fen}
Board visualization:
{board_state}

Legal moves available:
{legal_moves_text}

Choose your next move from the legal moves above.
Respond with ONLY your chosen move in UCI notation (e.g., 'e2e4').
Do not include any other text in your response."""

                # Get response from team
                try:
                    response = st.session_state.agent.run(
                        move_request,
                        stream=False,
                        dependencies={
                            "current_player": current_agent_name,
                            "board_state": board_state,
                            "legal_moves": legal_moves,
                        },
                    )

                    # Parse and validate move
                    move_str = parse_move(response.content if response else "")
                    legal_move_ucis = [move["uci"] for move in legal_moves]

                    if move_str in legal_move_ucis:
                        valid_uci_move = move_str
                    else:
                        valid_uci_move = find_move_from_san(move_str, legal_moves)

                    if valid_uci_move:
                        success, message = chess_board.make_move(valid_uci_move)

                        if success:
                            # Record move
                            move_description = next(
                                (
                                    move["description"]
                                    for move in legal_moves
                                    if move["uci"] == valid_uci_move
                                ),
                                valid_uci_move,
                            )

                            move_number = len(st.session_state.move_history) + 1
                            current_model = (
                                selected_white
                                if current_color == WHITE
                                else selected_black
                            )

                            st.session_state.move_history.append(
                                {
                                    "number": move_number,
                                    "player": f"{current_color.capitalize()} ({current_model})",
                                    "move": valid_uci_move,
                                    "description": move_description,
                                }
                            )

                            # Check if game is now over
                            game_over_now, _ = chess_board.get_game_state()
                            if game_over_now:
                                st.session_state.game_paused = True

                            st.rerun()
                        else:
                            st.error(f"Failed to make move {valid_uci_move}: {message}")
                    else:
                        st.error(
                            f"Invalid move returned: '{move_str}' - not found in legal moves"
                        )

                except Exception as e:
                    st.error(f"Error getting move: {str(e)}")
    else:
        st.info("👈 Press 'Start Game' to begin the chess match!")


if __name__ == "__main__":
    main()
