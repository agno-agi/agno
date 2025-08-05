from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    output_model=OpenAIChat(id="o3-mini"),
)

agent.print_response("What is the capital of France?")
