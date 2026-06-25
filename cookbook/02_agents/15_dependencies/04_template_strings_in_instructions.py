"""
Template Strings In Instructions
=============================

Dependency values are substituted into instructions, system messages, and
additional context using `{key}` syntax. The agent resolves these at run
start when `resolve_in_context` is True (the default).

This avoids the need for `add_dependencies_to_context=True` when you only
want a couple of values placed in specific spots — the templating is more
precise.

Pitfall: keys that don't exist in dependencies or session_state raise an
error. Only reference keys you know are populated.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


def get_user_profile() -> dict:
    return {
        "name": "Alex Chen",
        "role": "Senior Data Scientist",
        "team": "Recommendations",
    }


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    dependencies={
        "user_profile": get_user_profile,
        "tone": "concise",
    },
    instructions=[
        "You are responding to {user_profile}.",
        "Always use a {tone} tone.",
    ],
    # Default is True; shown explicitly here for clarity
    resolve_in_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What should I focus on this week?")
