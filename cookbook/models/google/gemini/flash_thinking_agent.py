from agno.agent import Agent
from agno.models.google import Gemini

task = (
    "Three missionaries and three cannibals need to cross a river. "
    "They have a boat that can carry up to two people at a time. "
    "If, at any time, the cannibals outnumber the missionaries on either side of the river, the cannibals will eat the missionaries. "
    "How can all six people get across the river safely? Provide a step-by-step solution and show the solutions as an ascii diagram"
)

agent = Agent(model=Gemini(id="gemini-2.0-flash-thinking-exp-1219"), markdown=True)
agent.print_response(task, stream=True)
