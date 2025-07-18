from agno.agent import Agent


def test_agent_with_state_in_messages():
    # Define a tool that increments our counter and returns the new value
    def add_item(agent: Agent, item: str) -> str:
        """Add an item to the shopping list."""
        agent.session_state["shopping_list"].append(item)
        return f"The shopping list is now {agent.session_state['shopping_list']}"

    # Create an Agent that maintains state
    agent = Agent(
        session_state={"shopping_list": []},
        tools=[add_item],
        instructions="Current state (shopping list) is: {shopping_list}",
        # Add the state to the messages
        add_state_in_messages=True,
        markdown=True,
    )
    agent.run("Add oranges to my shopping list")
    response = agent.run(
        'Current shopping list: {shopping_list}. Other random json ```json { "properties": { "title": { "title": "a" } } }```'
    )
    assert (
        response.messages[1].content
        == 'Current shopping list: [\'oranges\']. Other random json ```json { "properties": { "title": { "title": "a" } } }```'
    )
