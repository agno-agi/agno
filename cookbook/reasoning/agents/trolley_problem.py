from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)
agent.print_response(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. "
    "Include an ASCII diagram of your solution.",
    stream=True,
    show_full_reasoning=True,
)
