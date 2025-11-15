from agno.agent import Agent
from agno.models.ollama.chat import Ollama
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

reasoning_agent = Agent(
    model=Ollama(id="llama3.2:latest"),
    tools=[
        ReasoningTools(
            enable_think=True,
            enable_analyze=True,
            add_instructions=True,
            add_few_shot=True,
        ),
        DuckDuckGoTools(),
    ],
    instructions="Use tables where possible",
    markdown=True,
)
reasoning_agent.print_response(
    "Write a report comparing NVDA to TSLA",
    stream=True,
    show_full_reasoning=True,
)
