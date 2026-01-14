from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import RetryAgentRun
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools import FunctionCall, tool
from agno.utils.log import logger


def post_hook(run_context: RunContext, fc: FunctionCall):
    logger.info(f"Post-hook: {fc.function.name}")
    logger.info(f"Arguments: {fc.arguments}")

    if run_context.session_state is None:
        run_context.session_state = {}

    shopping_list = (
        run_context.session_state.get("shopping_list", [])
        if run_context.session_state
        else []
    )
    if len(shopping_list) < 3:
        raise RetryAgentRun(
            f"Shopping list is: {shopping_list}. Minimum 3 items in the shopping list. "
            + f"Add {3 - len(shopping_list)} more items."
        )


@tool(post_hook=post_hook)
def add_item(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if "shopping_list" not in run_context.session_state:
        run_context.session_state["shopping_list"] = []

    run_context.session_state["shopping_list"].append(item)
    return f"The shopping list is now {run_context.session_state['shopping_list']}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    session_id="retry_tool_call_from_post_hook_session",
    db=SqliteDb(
        session_table="retry_tool_call_from_post_hook_session",
        db_file="tmp/retry_tool_call_from_post_hook.db",
    ),
    # Initialize the session state with empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item],
    markdown=True,
)
agent.print_response("Add milk", stream=True)
print(
    f"Final session state: {agent.get_session_state(session_id='retry_tool_call_from_post_hook_session')}"
)
