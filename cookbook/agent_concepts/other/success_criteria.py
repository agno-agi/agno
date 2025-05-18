from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools

thinking_agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    tools=[
        ThinkingTools(add_instructions=True),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables where possible",
    show_tool_calls=True,
    markdown=True,
    stream_intermediate_steps=True,
    success_criteria="just give stock price ",
)
thinking_agent.print_response(
    "nvidia vs tesla", stream=True, show_reasoning=True
)
