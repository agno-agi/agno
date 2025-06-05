from agno.agent import Agent
from agno.models.xai import xAI
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=xAI(id="grok-3-beta"),
    tools=[
        ReasoningTools(add_instructions=True, add_few_shot=True),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions=[
        "Use tables to display data",
        "Only output the report, no other text",
    ],
    markdown=True,
)
reasoning_agent.print_response(
    "Write a report on TSLA",
    stream=True,
    show_full_reasoning=True,
    stream_intermediate_steps=True,
)
