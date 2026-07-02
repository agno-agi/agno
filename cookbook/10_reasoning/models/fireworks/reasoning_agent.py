from agno.agent import Agent
from agno.models.fireworks import Fireworks

task = (
    "Three missionaries and three cannibals need to cross a river. "
    "They have a boat that can carry up to two people at a time. "
    "If, at any time, the cannibals outnumber the missionaries on either side of the river, the cannibals will eat the missionaries. "
    "How can all six people get across the river safely? Provide a step-by-step solution and show the state after each crossing."
)

agent = Agent(
    model=Fireworks(id="accounts/fireworks/models/qwen3-30b-a3b"),
    reasoning=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(task, stream=True, show_full_reasoning=True)
