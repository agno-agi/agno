from agno.agent import Agent
from agno.models.azure.openai_chat import AzureOpenAI
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=AzureOpenAI(id="gpt-4o-mini"),
    tools=[
        ReasoningTools(
            think=True,
            analyze=True,
            add_instructions=True,
            add_few_shot=True,
        ),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables where possible. Think about the problem step by step.",
    markdown=True,
    debug_mode=True,
)
reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA.",
    stream=True,
    show_full_reasoning=True,
    stream_intermediate_steps=True,
)
