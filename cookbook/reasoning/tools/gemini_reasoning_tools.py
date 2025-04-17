from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=Gemini(id="gemini-2.5-pro-preview-03-25"),
    tools=[
        ReasoningTools(
            think=True,
            analyze=True,
            add_instructions=True,
        ),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables where possible",
    stream_intermediate_steps=True,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)
reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA.", show_full_reasoning=True
)
