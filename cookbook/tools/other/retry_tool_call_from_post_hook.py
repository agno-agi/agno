from agno.agent import Agent
from agno.exceptions import RetryAgentRun
from agno.models.openai import OpenAIChat
from agno.tools import FunctionCall, tool
from agno.utils.log import logger


def post_hook(session_state: dict, fc: FunctionCall):
    logger.info(f"Post-hook: {fc.function.name}")
    logger.info(f"Arguments: {fc.arguments}")
    shopping_list = session_state.get("shopping_list", []) if session_state else []
    if len(shopping_list) < 3:
        raise RetryAgentRun(
            f"Shopping list is: {shopping_list}. Minimum 3 items in the shopping list. "
            + f"Add {3 - len(shopping_list)} more items."
        )


@tool(post_hook=post_hook)
def add_item(session_state: dict, item: str) -> str:
    """Add an item to the shopping list."""
    if session_state:
        session_state["shopping_list"].append(item)
        return f"The shopping list is now {session_state['shopping_list']}"
    return ""


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Initialize the session state with empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item],
    markdown=True,
)
agent.print_response("Add milk", stream=True)
print(f"Final session state: {agent.get_session_state()}")
