from agno.agent import Agent
from agno.models.azure.openai_chat import AzureOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

reasoning_agent = Agent(
    model=AzureOpenAI(id="gpt-4o-mini"),
    tools=[
        DuckDuckGoTools(),
        ReasoningTools(
            enable_think=True,
            enable_analyze=True,
            add_instructions=True,
            add_few_shot=True,
        ),
    ],
    instructions="Use tables where possible. Think about the problem step by step.",
    markdown=True,
)

reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA.",
    stream=True,
    show_full_reasoning=True,
)
