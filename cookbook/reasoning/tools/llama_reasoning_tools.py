from agno.agent import Agent
from agno.models.meta import Llama
from agno.models.meta.llama_openai import LlamaOpenAI
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
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
    instructions="Use tables where possible",
    markdown=True,
    show_tool_calls=True
)
reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA",
    stream=True,
    show_full_reasoning=True,
    stream_intermediate_steps=True,
)
