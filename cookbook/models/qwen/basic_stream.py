from agno.agent import Agent
from agno.models.qwen import Qwen

agent = Agent(model=Qwen(id="qwen-max"), markdown=True)

agent.print_response("Tell a short story about AI and human collaboration", stream=True) 