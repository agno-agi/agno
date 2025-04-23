import os

from agno.agent import Agent
from agno.models.azure import AzureAIFoundry

agent = Agent(
    model=AzureAIFoundry(id="gpt-4o"),
    reasoning=True,
    reasoning_model=AzureAIFoundry(
        id="DeepSeek-R1",
        azure_endpoint=os.getenv("AZURE_ENDPOINT"),
        api_key=os.getenv("AZURE_API_KEY"),
    ),
)

agent.print_response(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. "
    "Include an ASCII diagram of your solution.",
    stream=True,
)
