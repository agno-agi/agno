from agno.agent import Agent
from agno.models.openai.responses import OpenAIResponses

agent = Agent(model=OpenAIResponses(id="o4-mini"))
agent.print_response(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. "
    "Include an ASCII diagram of your solution.",
    stream=True,
)
