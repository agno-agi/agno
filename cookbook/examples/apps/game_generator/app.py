from pathlib import Path

import streamlit as st
from agno.utils.string import hash_string_sha256
from game_generator import GameGenerator, SqliteWorkflowStorage

st.set_page_config(
    page_title="HTML5 Game Generator",
    page_icon="🎮",
    layout="wide",
)


st.title("Game Generator")
st.markdown("##### 🎮 built using [Agno](https://github.com/agno-agi/agno)")


def main() -> None:
    game_description = st.sidebar.text_area(
        "🎮 Describe your game",
        value="An asteroids game. Make sure the asteroids move randomly and are random sizes.",
        height=100,
    )

    generate_game = st.sidebar.button("Generate Game! 🚀")

    st.sidebar.markdown("## Example Games")
    example_games = [
        "A simple snake game where the snake grows longer as it eats food",
        "A breakout clone with colorful blocks and power-ups",
        "A space invaders game with multiple enemy types",
        "A simple platformer with jumping mechanics",
    ]

    for game in example_games:
        if st.sidebar.button(game):
            st.session_state["game_description"] = game
            generate_game = True

    if generate_game:
        with st.spinner("Generating your game... This might take a minute..."):
            try:
                hash_of_description = hash_string_sha256(game_description)
                game_generator = GameGenerator(
                    session_id=f"game-gen-{hash_of_description}",
                    storage=SqliteWorkflowStorage(
                        table_name="game_generator_workflows",
                        db_file="tmp/workflows.db",
                    ),
                )

                result = list(game_generator.run(game_description=game_description))

                games_dir = Path(__file__).parent.joinpath("games")
                game_path = games_dir / "game_output_file.html"

                if game_path.exists():
                    game_code = game_path.read_text()

                    with st.status(
                        "Game Generated Successfully!", expanded=True
                    ) as status:
                        st.subheader("Play the Game")
                        st.components.v1.html(game_code, height=700, scrolling=False)

                        st.subheader("Game Instructions")
                        st.write(result[-1].content)

                        st.download_button(
                            label="Download Game HTML",
                            data=game_code,
                            file_name="game.html",
                            mime="text/html",
                        )

                        status.update(
                            label="Game ready to play!",
                            state="complete",
                            expanded=True,
                        )

            except Exception as e:
                st.error(f"Failed to generate game: {str(e)}")

    st.sidebar.markdown("---")
    if st.sidebar.button("Restart"):
        st.rerun()


main()
