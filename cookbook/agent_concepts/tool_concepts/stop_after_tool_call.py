from agno.agent import Agent
from agno.tools import tool


@tool(show_result=True, stop_after_tool_call=True)
def get_answer_to_life_universe_and_everything() -> str:
    """
    This returns the answer to the life, the universe and everything.
    """
    return "42"


agent = Agent(
    tools=[get_answer_to_life_universe_and_everything],
    markdown=True,
    show_tool_calls=True,
)
agent.print_response("What is the answer to life, the universe and everything?")
