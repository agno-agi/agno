"""
Parallel Company Research
=============================

Deep research with structured output and citations.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Deep research with default settings
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_task=True)],
    markdown=True,
)

# Example 2: Research with higher quality processor
thorough_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_task=True,
            default_processor="pro",
        )
    ],
    markdown=True,
)

# Example 3: Research with structured output schema
structured_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_task=True,
            default_output_schema={
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "valuation": {"type": "string"},
                    "latest_funding": {"type": "string"},
                    "key_investors": {"type": "array", "items": {"type": "string"}},
                },
            },
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Research the current state of quantum computing. "
        "Find the leading companies, their latest achievements, and funding amounts. "
        "Provide sources for each claim.",
        stream=True,
    )
