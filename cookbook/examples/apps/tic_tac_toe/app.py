import re

import nest_asyncio
import streamlit as st
from agents import get_tic_tac_toe_team
from agno.utils.log import logger

from utils import (
    CUSTOM_CSS,
    TicTacToeBoard,
    display_board,
    display_move_history,
    show_agent_status,
)

nest_asyncio.apply()

# Page configuration
st.set_page_config(
    page_title="Agent Tic Tac Toe",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS with dark mode support
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>Agents play Tic Tac Toe</h1>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Initialize session state
    ####################################################################
    if "game_started" not in st.session_state:
        st.session_state.game_started = False
        st.session_state.game_paused = False
        st.session_state.move_history = []
        st.session_state.error_state = False

    with st.sidebar:
        st.markdown("### Game Controls")
        model_options = {
            "gpt-4o": "openai:gpt-4o",
            "gpt-4.5": "openai:gpt-4.5-preview",
            "o3-mini": "openai:o3-mini",
            "claude-3.5": "anthropic:claude-3-5-sonnet",
            "claude-3.7": "anthropic:claude-3-7-sonnet",
            "claude-3.7-thinking": "anthropic:claude-3-7-sonnet-thinking",
            "gemini-flash": "google:gemini-2.0-flash",
            "gemini-pro": "google:gemini-2.0-pro-exp-02-05",
            "llama-3.3": "groq:llama-3.3-70b-versatile",
        }
        ################################################################
        # Model selection
        ################################################################
        selected_p_x = st.selectbox(
            "Select Player X",
            list(model_options.keys()),
            index=list(model_options.keys()).index("gpt-4o"),
            key="model_p1",
        )
        selected_p_o = st.selectbox(
            "Select Player O",
            list(model_options.keys()),
            index=list(model_options.keys()).index("claude-3.7"),
            key="model_p2",
        )
        selected_referee = st.selectbox(
            "Select Referee",
            list(model_options.keys()),
            index=list(model_options.keys()).index("gpt-4o"),
            key="model_referee",
        )

        ################################################################
        # Game controls
        ################################################################
        col1, col2 = st.columns(2)
        with col1:
            if not st.session_state.game_started:
                if st.button("▶️ Start Game"):
                    try:
                        st.session_state.team = get_tic_tac_toe_team(
                            model_x=model_options[selected_p_x],
                            model_o=model_options[selected_p_o],
                            referee_model=model_options[selected_referee],
                            debug_mode=True,
                        )
                        st.session_state.game_board = TicTacToeBoard()
                        st.session_state.game_started = True
                        st.session_state.game_paused = False
                        st.session_state.move_history = []
                        st.session_state.error_state = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to initialize game: {str(e)}")
                        st.session_state.error_state = True
                        st.session_state.game_started = False
                        return
            else:
                game_over, _ = st.session_state.game_board.get_game_state()
                if not game_over:
                    if st.button(
                        "⏸️ Pause" if not st.session_state.game_paused else "▶️ Resume"
                    ):
                        st.session_state.game_paused = not st.session_state.game_paused
                        st.rerun()
        with col2:
            if st.session_state.game_started:
                if st.button("🔄 New Game"):
                    try:
                        st.session_state.team = get_tic_tac_toe_team(
                            model_x=model_options[selected_p_x],
                            model_o=model_options[selected_p_o],
                            referee_model=model_options[selected_referee],
                            debug_mode=True,
                        )
                        st.session_state.game_board = TicTacToeBoard()
                        st.session_state.game_paused = False
                        st.session_state.move_history = []
                        st.session_state.error_state = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to initialize game: {str(e)}")
                        st.session_state.error_state = True
                        st.session_state.game_started = False
                        return

    ####################################################################
    # Header showing current models
    ####################################################################
    if st.session_state.game_started:
        st.markdown(
            f"<h3 style='color:#87CEEB; text-align:center;'>{selected_p_x} vs {selected_p_o} (Referee: {selected_referee})</h3>",
            unsafe_allow_html=True,
        )

    ####################################################################
    # Main game area
    ####################################################################
    if st.session_state.game_started and not st.session_state.error_state:
        game_over, status = st.session_state.game_board.get_game_state()

        display_board(st.session_state.game_board)

        # Show game status (winner/draw/current player)
        if game_over:
            winner_player = (
                "X" if "X wins" in status else "O" if "O wins" in status else None
            )
            if winner_player:
                winner_num = "1" if winner_player == "X" else "2"
                winner_model = selected_p_x if winner_player == "X" else selected_p_o
                st.success(f"🏆 Game Over! Player {winner_num} ({winner_model}) wins!")
            else:
                st.info("🤝 Game Over! It's a draw!")
        else:
            # Show current player status
            current_player = st.session_state.game_board.current_player
            player_num = "1" if current_player == "X" else "2"
            current_model_name = selected_p_x if current_player == "X" else selected_p_o

            show_agent_status(
                f"Player {player_num} ({current_model_name})",
                "It's your turn",
            )

        display_move_history()

        if not st.session_state.game_paused and not game_over:
            # Thinking indicator
            st.markdown(
                f"""<div class="thinking-container">
                    <div class="agent-thinking">
                        <div style="margin-right: 10px; display: inline-block;">🔄</div>
                        Player {player_num} ({current_model_name}) is thinking...
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

            valid_moves = st.session_state.game_board.get_valid_moves()
            current_player_name = "Player X" if current_player == "X" else "Player O"

            # Create the context for the team - using only serializable data
            context = {
                "current_player": current_player_name,
                "board_state": str(st.session_state.game_board.get_board_state()),
                "valid_moves": [
                    list(move) for move in valid_moves
                ],  # Convert tuples to lists
                "game_state": {
                    "current_player": current_player_name,
                    "board": str(st.session_state.game_board.get_board_state()),
                    "valid_moves": [list(move) for move in valid_moves],
                },
            }

            # Get move from the team
            max_retries = 3
            retry_count = 0
            last_error = None

            while retry_count < max_retries:
                try:
                    # Add retry information to context if this is a retry
                    if retry_count > 0:
                        context["retry_info"] = {
                            "attempt": retry_count + 1,
                            "max_attempts": max_retries,
                            "last_error": str(last_error),
                        }
                        prompt = f"""\
Current board state:\n{context["board_state"]}\n
Available valid moves (row, col): {context["valid_moves"]}\n
You are {current_player_name}. This is attempt {retry_count + 1} of {max_retries}.
Previous attempt failed because: {last_error}
Choose your next move from the valid moves above.
Respond with ONLY two numbers for row and column, e.g. "1 2"."""
                    else:
                        prompt = f"""\
Current board state:\n{context["board_state"]}\n
Available valid moves (row, col): {context["valid_moves"]}\n
You are {current_player_name}. Choose your next move from the valid moves above.
Respond with ONLY two numbers for row and column, e.g. "1 2"."""

                    response = st.session_state.team.run(
                        prompt,
                        context=context,
                        stream=False,
                    )

                    if not response or not response.content:
                        raise Exception("No response received from agent")

                    numbers = re.findall(r"\d+", response.content)
                    if len(numbers) < 2:
                        raise Exception("Invalid move format received from agent")

                    row, col = map(int, numbers[:2])
                    success, message = st.session_state.game_board.make_move(row, col)

                    if success:
                        move_number = len(st.session_state.move_history) + 1
                        st.session_state.move_history.append(
                            {
                                "number": move_number,
                                "player": f"Player {player_num} ({current_model_name})",
                                "move": f"{row},{col}",
                            }
                        )

                        logger.info(
                            f"Move {move_number}: Player {player_num} ({current_model_name}) placed at position ({row}, {col})"
                        )
                        logger.info(
                            f"Board state:\n{st.session_state.game_board.get_board_state()}"
                        )

                        # Check game state after move
                        game_over, status = st.session_state.game_board.get_game_state()
                        if game_over:
                            logger.info(f"Game Over - {status}")
                            if "wins" in status:
                                st.success(f"🏆 Game Over! {status}")
                            else:
                                st.info(f"🤝 Game Over! {status}")
                            st.session_state.game_paused = True
                        st.rerun()
                        break  # Exit the retry loop on success
                    else:
                        last_error = message
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise Exception(
                                f"Failed after {max_retries} attempts. Last error: {message}"
                            )
                        logger.warning(
                            f"Invalid move attempt {retry_count}: {message}. Retrying..."
                        )
                        continue

                except Exception as e:
                    last_error = str(e)
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(
                            f"Error processing move after {max_retries} attempts: {str(e)}"
                        )
                        st.error(
                            f"Error processing move after {max_retries} attempts: {str(e)}"
                        )
                        st.session_state.error_state = True
                        st.session_state.game_paused = True
                        return
                    logger.warning(
                        f"Error on attempt {retry_count}: {str(e)}. Retrying..."
                    )
                    continue

            # If we get here with retry_count >= max_retries, it means all retries failed
            if retry_count >= max_retries:
                logger.error(
                    f"Failed to make a valid move after {max_retries} attempts"
                )
                st.error(f"Failed to make a valid move after {max_retries} attempts")
                st.session_state.error_state = True
                st.session_state.game_paused = True
                return
    else:
        if st.session_state.error_state:
            st.error("Game stopped due to an error. Please start a new game.")
        else:
            st.info("👈 Press 'Start Game' to begin!")

    ####################################################################
    # About section
    ####################################################################
    st.sidebar.markdown(f"""
    ### 🎮 Agent Tic Tac Toe Battle
    Watch two agents compete in real-time!

    **Current Players:**
    * 🔵 Player X: `{selected_p_x}`
    * 🔴 Player O: `{selected_p_o}`
    * 🎯 Referee: `{selected_referee}`

    **How it Works:**
    Each Agent analyzes the board and employs strategic thinking to:
    * 🏆 Find winning moves
    * 🛡️ Block opponent victories
    * ⭐ Control strategic positions
    * 🤔 Plan multiple moves ahead

    Built with Streamlit and Agno
    """)


if __name__ == "__main__":
    main()
