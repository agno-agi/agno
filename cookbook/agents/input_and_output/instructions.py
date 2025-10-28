from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext


def get_run_instructions(run_context: RunContext) -> str:
    """Build instructions for the Agent based on the run context."""
    if not run_context.session_state:
        return (
            "You are a helpful assistant that can answer questions and help with tasks."
        )

    user_name = run_context.session_state.get("user_name", "")
    user_sentiment = run_context.session_state.get("user_sentiment", "")

    return dedent(
        f"""
        You are a helpful assistant that can answer questions and help with tasks.
        The user name is {user_name}, and its current sentiment is {user_sentiment}.
        Please take the current sentiment into account when answering questions and helping with tasks."""
    )


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions=get_run_instructions,  # We set the instructions to our function. It will be resolved when running the agent.
)

response = agent.run(
    "Hey, what is my name?",
    # Adding some user information to the session state. This will propagate to our instructions function.
    session_state={"user_name": "John Doe", "user_sentiment": "Positive"},
)

print(response.content)
