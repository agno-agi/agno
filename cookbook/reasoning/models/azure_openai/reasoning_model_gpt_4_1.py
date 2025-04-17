from agno.agent import Agent
from agno.models.azure.openai_chat import AzureOpenAI

agent = Agent(
    model=AzureOpenAI(id="gpt-4o-mini"), reasoning_model=AzureOpenAI(id="gpt-4.1")
)
agent.print_response(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. "
    "Include an ASCII diagram of your solution.",
    stream=True,
)
