from typing import List

from agno.agent import Agent


def get_instructions(agent: Agent) -> List[str]:
    return [
        f"Your name is {agent.name}!",
        "Talk in haiku's!",
        "Use poetry to answer questions.",
    ]


agent = Agent(
    name="AgentX",
    instructions=get_instructions,
    markdown=True,
    show_tool_calls=True,
)
agent.print_response("Who are you?", stream=True)
