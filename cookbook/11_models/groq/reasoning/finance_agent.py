from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.yfinance import YFinanceTools

# Create an Agent with Groq and YFinanceTools
finance_agent = Agent(
    model=Groq(id="deepseek-r1-distill-llama-70b-specdec"),
    tools=[YFinanceTools()],
    description="You are an investment analyst with deep expertise in market analysis",
    instructions=[
        "Use tables to display data where possible.",
        "Always call the tool before you answer.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# Example usage
finance_agent.print_response(
    "Write a report on NVDA with stock price, analyst recommendations, and stock fundamentals.",
    stream=True,
)
