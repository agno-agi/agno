"""
Instructions With State
=============================

Example demonstrating how to use a function as instructions for an agent.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext


# This will be our instructions function
def get_run_instructions(run_context: RunContext) -> str:
    """Build instructions for the Agent based on the run context."""
    if not run_context.session_state:
        return "You are a helpful game development assistant that can answer questions about coding and game design."

    game_genre = run_context.session_state.get("game_genre", "")
    difficulty_level = run_context.session_state.get("difficulty_level", "")

    return dedent(
        f"""
        You are a specialized game development assistant.
        The team is currently working on a {game_genre} game.
        The current project difficulty level is set to {difficulty_level}.
        Please tailor your responses to match this genre and complexity level when providing
        coding advice, design suggestions, or technical guidance."""
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
game_development_agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=get_run_instructions,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    game_development_agent.print_response(
        "What genre are we working on and what should I focus on for the core mechanics?",
        session_state={"game_genre": "platformer", "difficulty_level": "hard"},
    )
