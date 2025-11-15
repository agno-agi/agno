from agno.agent import Agent
from agno.models.meta import Llama
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[
        ReasoningTools(
            enable_think=True,
            enable_analyze=True,
            add_instructions=True,
        ),
        YFinanceTools(),
    ],
    instructions="Use tables where possible",
    markdown=True,
)
reasoning_agent.print_response(
    "What is the NVDA stock price? Write me a report",
    show_full_reasoning=True,
)
