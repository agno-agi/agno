from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext


def get_user_profile(run_context: RunContext) -> dict:
    """Get the user profile from the run context."""
    if not run_context.session_state:
        return {}

    return {
        "name": run_context.session_state.get("user_name", ""),
        "email": run_context.session_state.get("user_email", ""),
    }


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    dependencies={"get_user_profile": get_user_profile},
    add_dependencies_to_context=True,
)

response = agent.run(
    "Get the user profile for the current session.",
    session_state={"user_name": "John Doe", "user_email": "john.doe@example.com"},
)

print(response.content)
