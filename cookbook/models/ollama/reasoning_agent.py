from agno.agent import Agent
from agno.models.ollama import Ollama

task = (
    "Three missionaries and three cannibals need to cross a river. "
    "They have a boat that can carry up to two people at a time. "
    "If, at any time, the cannibals outnumber the missionaries on either side of the river, the cannibals will eat the missionaries. "
    "How can all six people get across the river safely? Provide a step-by-step solution and show the solutions as an ascii diagram"
)

agent = Agent(
    model=Ollama(
        id="gpt-oss:20b",
    ),
    reasoning=True,
    markdown=True,
    debug_mode=True,
)
agent.print_response(task, stream=True)
