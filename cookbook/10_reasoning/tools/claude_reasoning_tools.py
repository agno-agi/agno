from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

reasoning_agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[
        ReasoningTools(add_instructions=True),
        DuckDuckGoTools(enable_search=True),
    ],
    instructions="Use tables to display data.",
    markdown=True,
)

# Semiconductor market analysis example
reasoning_agent.print_response(
    """\
    Analyze the semiconductor market performance focusing on:
    - NVIDIA (NVDA)
    - AMD (AMD)
    - Intel (INTC)
    - Taiwan Semiconductor (TSM)
    Compare their market positions, growth metrics, and future outlook.""",
    stream=True,
    show_full_reasoning=True,
)
