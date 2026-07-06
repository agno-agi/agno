"""Run: pip install wolframalpha agno"""

from agno.agent import Agent
from agno.tools.wolfram_alpha import WolframAlphaTools

agent = Agent(
    tools=[WolframAlphaTools()],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response("What is the integral of x^3 from 0 to 10?")
