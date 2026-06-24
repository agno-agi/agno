"""
Session State Tools
===================
Use `session_state` as a parameter name in your factory to receive
the session state dict directly (no need for run_context).

Set `cache_callables=False` so the factory runs fresh every time,
picking up any session_state changes between runs.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def get_greeting(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


def get_farewell(name: str) -> str:
    """Say goodbye to someone."""
    return f"Goodbye, {name}!"


def get_tools(session_state: dict):
    """Pick tools based on the 'mode' key in session_state."""
    mode = session_state.get("mode", "greet")
    print(f"--> Factory resolved mode: {mode}")

    if mode == "greet":
        return [get_greeting]
    else:
        return [get_farewell]


# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=get_tools,
    cache_callables=False,
    instructions=["Use the available tool to respond."],
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Greet mode ===")
    agent.print_response(
        "Say hi to Alice",
        session_state={"mode": "greet"},
        stream=True,
    )

    print("\n=== Farewell mode ===")
    agent.print_response(
        "Say bye to Alice",
        session_state={"mode": "farewell"},
        stream=True,
    )
