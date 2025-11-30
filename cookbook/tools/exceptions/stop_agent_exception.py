from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import StopAgentRun
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.utils.log import logger


def add_item(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if "shopping_list" not in run_context.session_state:
        run_context.session_state["shopping_list"] = []

    run_context.session_state["shopping_list"].append(item)
    len_shopping_list = len(run_context.session_state["shopping_list"])

    if len_shopping_list < 3:
        raise StopAgentRun(
            f"Shopping list is: {run_context.session_state['shopping_list']}. We must stop the agent."  # type: ignore
        )

    logger.info(
        f"The shopping list is now: {run_context.session_state.get('shopping_list')}"
    )  # type: ignore
    return f"The shopping list is now: {run_context.session_state.get('shopping_list')}"  # type: ignore


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    session_id="stop_agent_exception_session",
    db=SqliteDb(
        session_table="stop_agent_exception_session",
        db_file="tmp/stop_agent_exception.db",
    ),
    # Initialize the session state with empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item],
    markdown=True,
)
agent.print_response("Add milk", stream=True)
print(
    f"Final session state: {agent.get_session_state(session_id='stop_agent_exception_session')}"
)
