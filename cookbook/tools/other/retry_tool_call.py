from agno.agent import Agent
from agno.exceptions import RetryAgentRun
from agno.models.openai import OpenAIChat
from agno.utils.log import logger


def add_item(session_state: dict, item: str) -> str:
    """Add an item to the shopping list."""
    if session_state:
        session_state["shopping_list"].append(item)
        len_shopping_list = len(session_state["shopping_list"])
    if len_shopping_list < 3:
        logger.info(
            f"Asking the model to add {3 - len_shopping_list} more items to the shopping list."
        )
        raise RetryAgentRun(
            f"Shopping list is: {session_state['shopping_list']}. Minimum 3 items in the shopping list. "  # type: ignore
            + f"Add {3 - len_shopping_list} more items.",
        )

    logger.info(f"The shopping list is now: {session_state.get('shopping_list')}")  # type: ignore
    return f"The shopping list is now: {session_state.get('shopping_list')}"  # type: ignore


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Initialize the session state with empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item],
    markdown=True,
)
agent.print_response("Add milk", stream=True)
print(f"Final session state: {agent.get_session_state()}")
