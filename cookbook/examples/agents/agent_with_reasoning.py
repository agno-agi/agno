from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools

reasoning_agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    tools=[ParallelTools(), ReasoningTools(add_instructions=True)],
    instructions="Only include the final answer in your response. No yapping.",
    markdown=True,
)

reasoning_agent.print_response(
    "Write a report on continuous learning in AI systems.",
    stream=True,
    show_full_reasoning=True,
)
