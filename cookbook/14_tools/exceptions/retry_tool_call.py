from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import RetryAgentRun
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
        logger.info(
            f"Asking the model to add {3 - len_shopping_list} more items to the shopping list."
        )
        raise RetryAgentRun(
            f"Shopping list is: {run_context.session_state['shopping_list']}. Minimum 3 items in the shopping list. "
            + f"Add {3 - len_shopping_list} more items.",
        )

    logger.info(
        f"The shopping list is now: {run_context.session_state.get('shopping_list')}"
    )  # type: ignore
    return f"The shopping list is now: {run_context.session_state.get('shopping_list')}"  # type: ignore


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    session_id="retry_tool_call_session",
    db=SqliteDb(
        session_table="retry_tool_call_session",
        db_file="tmp/retry_tool_call.db",
    ),
    # Initialize the session state with empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item],
    markdown=True,
)
agent.print_response("Add milk", stream=True)
print(
    f"Final session state: {agent.get_session_state(session_id='retry_tool_call_session')}"
)
