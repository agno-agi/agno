"""Example demonstrating how to use a pre_hook to update the session_state."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.agent import RunContext


def transform_session_state(run_context: RunContext) -> None:
    """Simple pre-hook function to update the session_state."""

    if run_context.session_state is None:
        run_context.session_state = {}

    if run_context.session_state.get("run_count") is None:
        run_context.session_state["run_count"] = 0
    else:
        run_context.session_state["run_count"] += 1


# Create a financial advisor agent with comprehensive hooks
agent = Agent(
    name="Simple Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    pre_hooks=[transform_session_state],
    db=SqliteDb(db_file="test.db"),
)

agent.run(
    input="What can I make for dinner tonight?",
    session_id="test_session",
)
print(
    f"Current session state, after the first run: {agent.get_session_state(session_id='test_session')}"
)

agent.run(
    input="What is the weather in Tokyo?",
    session_id="test_session",
)
print(
    f"Current session state, after the second run: {agent.get_session_state(session_id='test_session')}"
)
