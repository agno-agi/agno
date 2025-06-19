from agno.agent import Agent
from agno.models.cloudflare import Cloudflare
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=Cloudflare(id="@cf/qwen/qwen1.5-7b-chat-awq"),
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
