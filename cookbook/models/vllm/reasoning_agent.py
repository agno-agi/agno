from agno.agent import Agent
from agno.models.vllm import vLLMOpenAI
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

reasoning_agent = Agent(
    model=vLLMOpenAI(id="Qwen/Qwen3-8B-FP8", top_k=20, enable_thinking=False),
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
