from agno.agent import Agent
from agno.exceptions import RetryAgentRun
from agno.models.openai import OpenAIChat
from agno.utils.log import logger


def add_item(agent: Agent, item: str) -> str:
    """Add an item to the shopping list."""
    agent.session_state["shopping_list"].append(item)
    len_shopping_list = len(agent.session_state["shopping_list"])
    if len_shopping_list < 3:
        logger.info(
            f"Asking the model to add {3 - len_shopping_list} more items to the shopping list."
        )
        raise RetryAgentRun(
            f"Shopping list is: {agent.session_state['shopping_list']}. Minimum 3 items in the shopping list. "
            + f"Add {3 - len_shopping_list} more items.",
        )

    logger.info(f"The shopping list is now: {agent.session_state.get('shopping_list')}")
    return f"The shopping list is now: {agent.session_state.get('shopping_list')}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Initialize the session state with empty shopping list
    session_state={"shopping_list": []},
    tools=[add_item],
    markdown=True,
)
agent.print_response("Add milk", stream=True)
print(f"Final session state: {agent.session_state}")
