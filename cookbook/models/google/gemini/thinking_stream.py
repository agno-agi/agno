from agno.agent import Agent
from agno.models.google import Gemini

model = Gemini(id="gemini-2.5-pro", thinking_budget=1000, include_thoughts=True)

agent = Agent(
    model=model,
    description="You are a problem-solving assistant that shows your reasoning.",
    markdown=True,
)

problem = """
A farmer has 17 sheep, and all but 9 die. How many sheep are left?
Think through this step by step and explain your reasoning.
"""

agent.print_response(problem, stream=True)
