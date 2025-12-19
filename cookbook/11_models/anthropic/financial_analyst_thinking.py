from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.calculator import CalculatorTools
from agno.tools.yfinance import YFinanceTools

# Complex multi-step reasoning problem that demonstrates interleaved thinking
task = (
    "I'm considering an investment portfolio. I want to invest $50,000 split equally "
    "between Apple (AAPL) and Tesla (TSLA). Calculate how many shares of each I can buy "
    "at current prices, then analyze what my total portfolio value would be if both stocks "
    "increased by 15%. Also calculate what percentage return that represents on my initial investment. "
    "Think through each step and show your reasoning process."
)

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        thinking={"type": "enabled", "budget_tokens": 2048},
        betas=["interleaved-thinking-2025-05-14"],
    ),
    tools=[
        CalculatorTools(),
        YFinanceTools(),
    ],
    instructions=[
        "You are a financial analysis assistant with access to calculator and stock price tools.",
        "For complex problems, think through each step carefully before and after using tools.",
        "Show your reasoning process and explain your calculations clearly.",
        "Use the calculator tool for all mathematical operations to ensure accuracy.",
    ],
    markdown=True,
)

agent.print_response(task, stream=True)
