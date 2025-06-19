from dataclasses import dataclass
from typing import Dict, List, Tuple

import chess
import streamlit as st
from agno.agent import Agent

WHITE = "white"
BLACK = "black"

# Custom CSS for the chess board
CUSTOM_CSS = """
<style>
    /* Dark mode styling */
    .main-title {
        color: #87CEEB;
        text-align: center;
        margin-bottom: 20px;
    }
    
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
    
    .move-history {
        margin-top: 20px;
        border: 1px solid #555;
        border-radius: 5px;
        padding: 10px;
        max-height: 300px;
        overflow-y: auto;
    }
    
    .move-entry {
        padding: 5px;
        border-bottom: 1px solid #444;
    }
    
    .move-entry:last-child {
        border-bottom: none;
    }
    
    .agent-thinking {
        display: flex;
        align-items: center;
        background-color: rgba(100, 100, 100, 0.2);
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
        animation: pulse 1.5s infinite;
    }
    
    @keyframes pulse {
        0% { opacity: 0.6; }
        50% { opacity: 1; }
        100% { opacity: 0.6; }
    }
    
    .agent-status {
        display: flex;
        align-items: center;
        background-color: rgba(100, 100, 100, 0.2);
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
    
    .agent-status.white {
        border-left: 4px solid #f0d9b5;
    }
    
    .agent-status.black {
        border-left: 4px solid #b58863;
    }
    
    .thinking-container {
        margin: 10px 0;
    }
    
    /* Additional CSS for the simple board representation */
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
    
    /* Additional CSS for move history grid */
    .move-history-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 10px;
        padding: 10px;
        max-height: 600px;  /* Height of approximately 2 rows of boards */
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: #666 #333;
    }
    
    /* Webkit scrollbar styling */
    .move-history-grid::-webkit-scrollbar {
        width: 8px;
    }

    .move-history-grid::-webkit-scrollbar-track {
        background: #333;
        border-radius: 4px;
    }

    .move-history-grid::-webkit-scrollbar-thumb {
        background: #666;
        border-radius: 4px;
    }

    .move-history-grid::-webkit-scrollbar-thumb:hover {
        background: #888;
    }
    
    .move-history-item {
        background: rgba(40, 40, 40, 0.8);
        border-radius: 5px;
        padding: 10px;
        text-align: center;
        border: 1px solid #444;
    }
    
    .move-history-item .move-text {
        font-family: monospace;
        font-size: 1.1em;
        margin: 5px 0;
    }

    .move-history-item .move-text.white-move {
        color: #4CAF50;
    }

    .move-history-item .move-text.black-move {
        color: #ff4444;
    }
    
    .move-history-item .description {
        color: #888;
        font-size: 0.9em;
        margin-top: 5px;
    }
    
    /* Mini chess board for history */
    .mini-chess-board {
        display: grid;
        grid-template-columns: repeat(8, 1fr);
        width: 160px;
        margin: 10px auto;
        border: 1px solid #555;
        position: relative;
    }
    
    .mini-square {
        aspect-ratio: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        position: relative;
    }
    
    .mini-white-square {
        background-color: #f0d9b5;
    }
    
    .mini-black-square {
        background-color: #b58863;
    }
    
    .mini-piece {
        font-size: 14px;
        line-height: 20px;
        z-index: 2;
    }

    .mini-piece.white-piece {
        color: #ffffff;
        text-shadow: 0 0 2px #000;
    }

    .mini-piece.black-piece {
        color: #000000;
        text-shadow: 0 0 2px #fff;
    }

    .mini-square.move-from.white-move {
        background-color: rgba(76, 175, 80, 0.5) !important;
    }

    .mini-square.move-to.white-move {
        background-color: rgba(76, 175, 80, 0.7) !important;
    }

    .mini-square.move-from.black-move {
        background-color: rgba(255, 68, 68, 0.5) !important;
    }

    .mini-square.move-to.black-move {
        background-color: rgba(255, 68, 68, 0.7) !important;
    }
</style>
"""


@dataclass
class SimpleChessBoard:
    """Represents a simple chess board state without full rules validation"""

    def __init__(self):
        # Use Unicode chess pieces for better visualization
        self.piece_map = {
            "K": "♔",
            "Q": "♕",
            "R": "♖",
            "B": "♗",
            "N": "♘",
            "P": "♙",  # White pieces
            "k": "♚",
            "q": "♛",
            "r": "♜",
            "b": "♝",
            "n": "♞",
            "p": "♟",  # Black pieces
            ".": " ",  # Empty square
        }

        self.board = [
            ["r", "n", "b", "q", "k", "b", "n", "r"],  # Black pieces
            ["p", "p", "p", "p", "p", "p", "p", "p"],  # Black pawns
            [".", ".", ".", ".", ".", ".", ".", "."],  # Empty row
            [".", ".", ".", ".", ".", ".", ".", "."],  # Empty row
            [".", ".", ".", ".", ".", ".", ".", "."],  # Empty row
            [".", ".", ".", ".", ".", ".", ".", "."],  # Empty row
            ["P", "P", "P", "P", "P", "P", "P", "P"],  # White pawns
            ["R", "N", "B", "Q", "K", "B", "N", "R"],  # White pieces
        ]

    def get_board_state(self) -> str:
        """Returns a formatted string representation of the current board state with HTML/CSS classes"""
        # First create the HTML structure with CSS classes
        html_output = [
            '<div class="chess-board-wrapper">',
            '<div class="chess-files">',
        ]

        # Add individual file labels
        for file in "abcdefgh":
            html_output.append(f'<div class="chess-file-label">{file}</div>')

        html_output.extend(
            [
                "</div>",  # Close chess-files
                '<div class="chess-grid">',
            ]
        )

        for i, row in enumerate(self.board):
            html_output.append('<div class="chess-row">')
            html_output.append(f'<div class="chess-rank">{8 - i}</div>')

            for piece in row:
                piece_char = self.piece_map[piece]
                piece_class = "piece-white" if piece.isupper() else "piece-black"
                if piece == ".":
                    piece_class = "piece-empty"
                html_output.append(
                    f'<div class="chess-cell {piece_class}">{piece_char}</div>'
                )

            html_output.append("</div>")

        html_output.append("</div>")
        html_output.append("</div>")

        return "\n".join(html_output)

    def update_position(
        self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]
    ) -> None:
        """Updates the board with a new move"""
        piece = self.board[from_pos[0]][from_pos[1]]
        self.board[from_pos[0]][from_pos[1]] = "."
        self.board[to_pos[0]][to_pos[1]] = piece

    def is_valid_position(self, pos: Tuple[int, int]) -> bool:
        """Checks if a position is within the board boundaries"""
        return 0 <= pos[0] < 8 and 0 <= pos[1] < 8

    def is_valid_move(self, move: str) -> bool:
        """Validates if a move string is in the correct format (e.g., 'e2e4')"""
        if len(move) != 4:
            return False

        file_chars = "abcdefgh"
        rank_chars = "12345678"

        from_file, from_rank = move[0], move[1]
        to_file, to_rank = move[2], move[3]

        return all(
            [
                from_file in file_chars,
                from_rank in rank_chars,
                to_file in file_chars,
                to_rank in rank_chars,
            ]
        )

    def algebraic_to_index(self, move: str) -> tuple[tuple[int, int], tuple[int, int]]:
        """Converts algebraic notation (e.g., 'e2e4') to board indices"""
        file_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 6, "h": 7}

        from_file, from_rank = move[0], int(move[1])
        to_file, to_rank = move[2], int(move[3])

        from_pos = (8 - from_rank, file_map[from_file])
        to_pos = (8 - to_rank, file_map[to_file])

        return from_pos, to_pos

    def get_piece_name(self, piece: str) -> str:
        """Returns the full name of a piece from its symbol"""
        piece_names = {
            "K": "King",
            "Q": "Queen",
            "R": "Rook",
            "B": "Bishop",
            "N": "Knight",
            "P": "Pawn",
            "k": "King",
            "q": "Queen",
            "r": "Rook",
            "b": "Bishop",
            "n": "Knight",
            "p": "Pawn",
            ".": "Empty",
        }
        return piece_names.get(piece, "Unknown")

    def get_piece_at_position(self, pos: Tuple[int, int]) -> str:
        """Returns the piece at the given position"""
        return self.board[pos[0]][pos[1]]


class ChessBoard:
    def __init__(self):
        self.board = chess.Board()
        self.current_color = WHITE
        self.move_history = []

    def make_move(self, move_str: str) -> Tuple[bool, str]:
        """
        Make a move on the board using python-chess for validation.

        Args:
            move_str: Move in UCI notation (e.g., "e2e4")

        Returns:
            Tuple[bool, str]: (Success status, Message with current board state or error)
        """
        try:
            # Convert to python-chess move
            move = chess.Move.from_uci(move_str)

            # Check if move is legal
            if move not in self.board.legal_moves:
                return False, f"Invalid move: {move_str} is not a legal move."

            self.board.push(move)

            # Switch player
            self.current_color = BLACK if self.current_color == WHITE else WHITE

            return True, f"Move successful!\n{self.get_board_state()}"
        except ValueError:
            return False, f"Invalid move format: {move_str}. Use format like 'e2e4'."
        except Exception as e:
            return False, f"Error making move: {str(e)}"

    def get_board_state(self) -> str:
        """
        Get a string representation of the current board state.

        Returns:
            String representation of the board
        """
        return str(self.board)

    def get_fen(self) -> str:
        """
        Get the FEN notation of the current board state.

        Returns:
            FEN string
        """
        return self.board.fen()

    def get_legal_moves(self, color: str = None) -> List[str]:
        """
        Get all legal moves for the current player or specified color.

        Args:
            color: Optional color to get moves for (WHITE or BLACK)

        Returns:
            List of legal moves in UCI notation
        """

        # If it's not the specified color's turn, return empty list
        if (color == WHITE and not self.board.turn) or (
            color == BLACK and self.board.turn
        ):
            return []

        return [move.uci() for move in self.board.legal_moves]

    def is_game_over(self) -> bool:
        """
        Check if the game is over.

        Returns:
            True if game is over, False otherwise
        """
        return self.board.is_game_over()

    def get_game_state(self) -> Tuple[bool, Dict]:
        """
        Get the current game state.

        Returns:
            Tuple[bool, Dict]: (is_game_over, state_info)
        """
        is_game_over = self.board.is_game_over()

        state_info = {
            "current_player": self.current_color,
            "fen": self.board.fen(),
            "halfmove_clock": self.board.halfmove_clock,
            "fullmove_number": self.board.fullmove_number,
        }

        if is_game_over:
            if self.board.is_checkmate():
                winner = BLACK if self.board.turn else WHITE
                state_info["result"] = f"{winner}_win"
                state_info["reason"] = "checkmate"
            elif self.board.is_stalemate():
                state_info["result"] = "draw"
                state_info["reason"] = "stalemate"
            elif self.board.is_insufficient_material():
                state_info["result"] = "draw"
                state_info["reason"] = "insufficient_material"
            elif self.board.is_fifty_moves():
                state_info["result"] = "draw"
                state_info["reason"] = "fifty_move_rule"
            elif self.board.is_repetition():
                state_info["result"] = "draw"
                state_info["reason"] = "repetition"
            else:
                state_info["result"] = "draw"
                state_info["reason"] = "unknown"
        else:
            state_info["result"] = None
            state_info["reason"] = None

        return is_game_over, state_info


def display_board(board: ChessBoard):
    """
    Display the chess board in the Streamlit app.

    Args:
        board: ChessBoard instance
    """
    board_obj = board.board

    # Create HTML for the chess board
    html = '<div class="chess-board">'

    # Unicode chess pieces
    pieces = {
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
        ".": "",
    }

    # Convert board to a 2D array for easier rendering
    board_array = []
    for row in str(board_obj).split("\n"):
        board_array.append(row.split(" "))

    for i in range(8):
        for j in range(8):
            square_color = "white-square" if (i + j) % 2 == 0 else "black-square"
            piece = board_array[i][j]
            piece_unicode = pieces.get(piece, "")

            html += f'<div class="chess-square {square_color}">'
            if piece_unicode:
                html += f'<span class="piece">{piece_unicode}</span>'
            html += "</div>"

    html += "</div>"

    st.markdown(html, unsafe_allow_html=True)


def show_agent_status(agent_name: str, status: str, is_white: bool = True):
    """
    Display the status of an agent.

    Args:
        agent_name: Name of the agent
        status: Status message
        is_white: Whether the agent plays white pieces
    """
    color_class = "white" if is_white else "black"
    st.markdown(
        f"""<div class="agent-status {color_class}">
            <div style="margin-right: 10px;">{"♔" if is_white else "♚"}</div>
            <div>
                <strong>{agent_name}</strong><br>
                {status}
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def display_move_history(move_history):
    """
    Display the move history with miniature chess boards.

    Args:
        move_history: List of move history entries
    """
    if not move_history:
        return

    st.markdown("<h3>Move History</h3>", unsafe_allow_html=True)

    html = '<div class="move-history-grid">'

    # Unicode chess pieces
    pieces = {
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
        ".": "",
    }

    for move in move_history:
        board = chess.Board()
        # Play all moves up to this point
        for i in range(move["number"]):
            if i < len(move_history):
                try:
                    board.push(chess.Move.from_uci(move_history[i]["move"]))
                except (chess.InvalidMoveError, ValueError) as e:
                    continue

        # Get the current move's from and to squares
        current_move = move["move"]
        from_square = current_move[:2]
        to_square = current_move[2:]

        # Convert algebraic notation to board coordinates
        file_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 6, "h": 7}
        from_file, from_rank = from_square[0], int(from_square[1])
        to_file, to_rank = to_square[0], int(to_square[1])
        from_coords = (8 - from_rank, file_map[from_file])
        to_coords = (8 - to_rank, file_map[to_file])

        # Determine if it's a white or black move
        is_white_move = "white" in move["player"].lower()
        move_color_class = "white-move" if is_white_move else "black-move"

        # Board to 2D array
        board_array = []
        for row in str(board).split("\n"):
            board_array.append(row.split(" "))

        # Create move history item with mini board
        html += '<div class="move-history-item">'
        html += f"<strong>Move {move['number']}</strong><br>"
        html += f"{move['player']}<br>"
        html += f'<div class="move-text {move_color_class}">{move["move"]}</div>'

        # Add mini chess board
        html += '<div class="mini-chess-board">'
        for i in range(8):
            for j in range(8):
                square_color = (
                    "mini-white-square" if (i + j) % 2 == 0 else "mini-black-square"
                )
                piece = board_array[i][j]
                piece_unicode = pieces.get(piece, "")

                # highlighting moves
                highlight_class = ""
                if (i, j) == from_coords:
                    highlight_class = f" move-from {move_color_class}"
                elif (i, j) == to_coords:
                    highlight_class = f" move-to {move_color_class}"

                html += f'<div class="mini-square {square_color}{highlight_class}">'
                if piece_unicode:
                    piece_color = "white-piece" if piece.isupper() else "black-piece"
                    html += (
                        f'<span class="mini-piece {piece_color}">{piece_unicode}</span>'
                    )
                html += "</div>"
        html += "</div>"

        if move.get("description"):
            html += f'<div class="description">{move["description"]}</div>'

        html += "</div>"

    html += "</div>"

    st.markdown(html, unsafe_allow_html=True)


def parse_move(move_text: str) -> str:
    """
    Parse a move from agent response.

    Args:
        move_text: Text containing the move

    Returns:
        Extracted move in UCI format
    """
    move_text = move_text.strip()

    # If the move is already in UCI format (e.g., "e2e4"), return it
    if (
        len(move_text) == 4
        and move_text[0].isalpha()
        and move_text[1].isdigit()
        and move_text[2].isalpha()
        and move_text[3].isdigit()
    ):
        return move_text

    # Try to extract the move from text
    import re

    move_match = re.search(r"([a-h][1-8][a-h][1-8])", move_text)
    if move_match:
        return move_match.group(1)

    return move_text


def is_claude_thinking_model(agent: Agent) -> bool:
    """
    Args:
        agent: The agent to check
    Returns:
        bool: True if the agent uses a Claude model with thinking enabled
    """
    return (
        hasattr(agent.model, "id")
        and isinstance(agent.model.id, str)
        and "claude" in agent.model.id.lower()
        and "thinking" in agent.model.id.lower()
    )
