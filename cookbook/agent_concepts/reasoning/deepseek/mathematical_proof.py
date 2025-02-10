from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.openai import OpenAIChat

task = "Prove that for any positive integer n, the sum of the first n odd numbers is equal to n squared. Provide a detailed proof."

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)
reasoning_agent.print_response(task, stream=True)
