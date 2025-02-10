from typing import Dict

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.log import logger
from chess_board import ChessBoard


class ChessGame:
    def __init__(self):
        self.board = ChessBoard()
        try:
            self.agents = self._initialize_agents()
        except Exception as e:
            logger.error(f"Failed to initialize agents: {str(e)}")
            raise

    def _initialize_agents(self) -> Dict[str, Agent]:
        """Initialize all required agents with specific roles"""
        try:
            legal_move_agent = Agent(
                name="legal_move_agent",
                role="""You are a chess rules expert. Given a board state and a color (white/black),
                       list ALL legal moves for that color in algebraic notation (e.g., 'e2e4').
                       Return the moves as a comma-separated list, for example:
                       'e2e4, d2d4, g1f3, b1c3'
                       Include all possible pawn moves, piece moves, castling if available.""",
                model=OpenAIChat(id="o3-mini"),
            )

            white_piece_agent = Agent(
                name="white_piece_agent",
                role="""You are a chess strategist for white pieces. Given a list of legal moves,
                       analyze them and choose the best one based on standard chess strategy.
                       Consider piece development, center control, and king safety.
                       Respond ONLY with your chosen move in algebraic notation (e.g., 'e2e4').""",
                model=OpenAIChat(id="o3-mini"),
            )

            black_piece_agent = Agent(
                name="black_piece_agent",
                role="""You are a chess strategist for black pieces. Given a list of legal moves,
                       analyze them and choose the best one based on standard chess strategy.
                       Consider piece development, center control, and king safety.
                       Respond ONLY with your chosen move in algebraic notation (e.g., 'e7e5').""",
                model=OpenAIChat(id="o3-mini"),
            )

            master_agent = Agent(
                name="master_agent",
                role="""You are a chess master overseeing the game. Your responsibilities:
                       1. Analyze the current board state to determine if the game has ended
                       2. Check for:
                         - Checkmate: If the king is in check and there are no legal moves
                         - Stalemate: If there are no legal moves but the king is not in check
                         - Draw: If there's insufficient material or threefold repetition
                       3. Provide a clear explanation of the game-ending condition if found
                       
                       Respond with one of these formats:
                       - "CONTINUE" if the game should continue
                       - "CHECKMATE - [color] wins" if there's a checkmate
                       - "STALEMATE" if there's a stalemate
                       - "DRAW - [reason]" if there's a draw""",
                instructions=[
                    "1. Coordinate the chess game by managing turns between white and black pieces",
                    "2. Get legal moves from legal_move_agent for current player",
                    "3. Pass legal moves to the current player's agent for selection",
                    "4. Update and maintain the board state after each valid move",
                    "5. Check for game-ending conditions after each move",
                ],
                model=OpenAIChat(id="o3-mini"),
                markdown=True,
                team=[white_piece_agent, black_piece_agent, legal_move_agent],
                show_tool_calls=True,
                debug_mode=True,
            )

            return {
                "white": white_piece_agent,
                "black": black_piece_agent,
                "legal": legal_move_agent,
                "master": master_agent,
            }
        except Exception as e:
            logger.error(f"Error initializing agents: {str(e)}")
            raise

    def start_game(self):
        """Start and manage the chess game"""
        try:
            initial_state = self.board.get_board_state()
            response = self.agents["master"].print_response(
                f"New chess game started. Current board state:\n{initial_state}\n"
                "Please manage the game, starting with white's move.",
                stream=True,
            )
            return response
        except Exception as e:
            print(f"Error starting game: {str(e)}")
            raise

    def make_move(self, move: str) -> Dict[str, str]:
        """Process a move and return the response with piece information"""
        try:
            if not self.board.is_valid_move(move):
                return {
                    "status": "Invalid move format. Please use algebraic notation (e.g., 'e2e4')"
                }

            from_pos, to_pos = self.board.algebraic_to_index(move)
            if not self.board.is_valid_position(
                from_pos
            ) or not self.board.is_valid_position(to_pos):
                return {"status": "Invalid move: Position out of bounds"}

            # Get piece information before moving
            piece = self.board.get_piece_at_position(from_pos)
            piece_name = self.board.get_piece_name(piece)

            # Only proceed if we have a valid piece (not empty or unknown)
            if piece_name in ["Empty", "Unknown"]:
                return {"status": f"Invalid move: No piece at position {move[:2]}"}

            # Make the move
            self.board.update_position(from_pos, to_pos)

            return {
                "status": "Move successful",
                "piece": piece,
                "piece_name": piece_name,
                "from": move[:2],
                "to": move[2:],
            }
        except Exception as e:
            return {"status": f"Error making move: {str(e)}"}


def main():
    try:
        game = ChessGame()
        game.start_game()
    except Exception as e:
        print(f"Fatal error: {str(e)}")


if __name__ == "__main__":
    main()
