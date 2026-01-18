from agno.agent import Agent
from agno.models.vercel import v0
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

reasoning_agent = Agent(
    model=v0(id="v0-1.0-md"),
    tools=[
        ReasoningTools(add_instructions=True, add_few_shot=True),
        DuckDuckGoTools(),
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
)
