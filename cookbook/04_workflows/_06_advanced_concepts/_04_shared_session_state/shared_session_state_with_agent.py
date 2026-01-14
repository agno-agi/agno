from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai.chat import OpenAIChat
from agno.run import RunContext
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

db = SqliteDb(db_file="tmp/workflow.db")


# Define tools to manage a shopping list in workflow session state
def add_item(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list in workflow session state.

    Args:
        item (str): The item to add to the shopping list
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    # Check if item already exists (case-insensitive)
    existing_items = [
        existing_item.lower()
        for existing_item in run_context.session_state["shopping_list"]
    ]
    if item.lower() not in existing_items:
        run_context.session_state["shopping_list"].append(item)
        return f"Added '{item}' to the shopping list."
    else:
        return f"'{item}' is already in the shopping list."


def remove_item(run_context: RunContext, item: str) -> str:
    """Remove an item from the shopping list in workflow session state.

    Args:
        item (str): The item to remove from the shopping list
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    if len(run_context.session_state["shopping_list"]) == 0:
        return f"Shopping list is empty. Cannot remove '{item}'."

    # Find and remove item (case-insensitive)
    shopping_list = run_context.session_state["shopping_list"]
    for i, existing_item in enumerate(shopping_list):
        if existing_item.lower() == item.lower():
            removed_item = shopping_list.pop(i)
            return f"Removed '{removed_item}' from the shopping list."

    return f"'{item}' not found in the shopping list."


def remove_all_items(run_context: RunContext) -> str:
    """Remove all items from the shopping list in workflow session state."""
    if run_context.session_state is None:
        run_context.session_state = {}

    run_context.session_state["shopping_list"] = []
    return "Removed all items from the shopping list."


def list_items(run_context: RunContext) -> str:
    """List all items in the shopping list from workflow session state."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if len(run_context.session_state["shopping_list"]) == 0:
        return "Shopping list is empty."

    items = run_context.session_state["shopping_list"]
    items_str = "\n".join([f"- {item}" for item in items])
    return f"Shopping list:\n{items_str}"


# Create agents with tools that use workflow session state
shopping_assistant = Agent(
    name="Shopping Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_item, remove_item, list_items],
    instructions=[
        "You are a helpful shopping assistant.",
        "You can help users manage their shopping list by adding, removing, and listing items.",
        "Always use the provided tools to interact with the shopping list.",
        "Be friendly and helpful in your responses.",
    ],
)

list_manager = Agent(
    name="List Manager",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[list_items, remove_all_items],
    instructions=[
        "You are a list management specialist.",
        "You can view the current shopping list and clear it when needed.",
        "Always show the current list when asked.",
        "Confirm actions clearly to the user.",
    ],
)

# Create steps
manage_items_step = Step(
    name="manage_items",
    description="Help manage shopping list items (add/remove)",
    agent=shopping_assistant,
)

view_list_step = Step(
    name="view_list",
    description="View and manage the complete shopping list",
    agent=list_manager,
)

# Create workflow with workflow_session_state
shopping_workflow = Workflow(
    name="Shopping List Workflow",
    db=db,
    steps=[manage_items_step, view_list_step],
    session_state={"shopping_list": []},
)

if __name__ == "__main__":
    # Example 1: Add items to the shopping list
    print("=== Example 1: Adding Items ===")
    shopping_workflow.print_response(
        input="Please add milk, bread, and eggs to my shopping list."
    )
    print("Workflow session state:", shopping_workflow.get_session_state())

    # Example 2: Add more items and view list
    print("\n=== Example 2: Adding More Items ===")
    shopping_workflow.print_response(
        input="Add apples and bananas to the list, then show me the complete list."
    )
    print("Workflow session state:", shopping_workflow.get_session_state())

    # Example 3: Remove items
    print("\n=== Example 3: Removing Items ===")
    shopping_workflow.print_response(
        input="Remove bread from the list and show me what's left."
    )
    print("Workflow session state:", shopping_workflow.get_session_state())

    # Example 4: Clear the entire list
    print("\n=== Example 4: Clearing List ===")
    shopping_workflow.print_response(
        input="Clear the entire shopping list and confirm it's empty."
    )
    print("Final workflow session state:", shopping_workflow.get_session_state())
