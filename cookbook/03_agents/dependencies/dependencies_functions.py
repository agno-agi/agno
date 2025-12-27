"""Example demonstrating how to read from the session state from a dependency function.

We will create a function that reads some fields from the session state and return them as a dictionary.
We will then use this function as a dependency in an agent, allowing us to get the session state data directly into the context.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext


def get_project_settings(run_context: RunContext) -> dict:
    """Get the current project settings from the session state."""
    if not run_context.session_state:
        return {}

    return {
        "project_name": run_context.session_state.get("project_name", ""),
        "theme": run_context.session_state.get("theme", "default"),
        "language": run_context.session_state.get("language", "en"),
    }


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    dependencies={"get_project_settings": get_project_settings},
    add_dependencies_to_context=True,
)

response = agent.print_response(
    "What are the current project settings? Please share them with me.",
    session_state={
        "project_name": "Analytics Dashboard",
        "theme": "dark",
        "language": "en",
    },
)
