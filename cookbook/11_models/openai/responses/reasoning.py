from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2", reasoning_effort="none"),
    tools=[YFinanceTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Solve the trolley problem. Evaluate multiple ethical frameworks. Include an ASCII diagram of your solution.", stream=True)
