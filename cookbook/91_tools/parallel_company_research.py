"""
Parallel Company Research
=============================

Deep research with structured output and citations using the Task API.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Output Schema Types
# ---------------------------------------------------------------------------
# The Task API supports three output schema formats:
#
# 1. Auto schema (default) - Let Parallel infer structure from the task
#    default_output_schema={"type": "auto"}
#
# 2. JSON schema - Enforce a specific structure with JSON Schema
#    default_output_schema={"type": "json", "json_schema": {...}}
#
# 3. String schema - Simple text description of expected output
#    default_output_schema="Return the company name, valuation, and investors"
# ---------------------------------------------------------------------------

# Example 1: Default settings (auto schema)
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_task=True)],
    markdown=True,
)

# Example 2: Higher quality processor (pro tier)
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

# Example 3: Explicit auto schema
auto_schema_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_task=True,
            default_output_schema={"type": "auto"},
        )
    ],
    markdown=True,
)

# Example 4: JSON schema for structured output
json_schema_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_task=True,
            default_output_schema={
                "type": "json",
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "company_name": {"type": "string"},
                        "valuation": {"type": "string"},
                        "latest_funding": {"type": "string"},
                        "key_investors": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        )
    ],
    markdown=True,
)

# Example 5: String schema (natural language description)
string_schema_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_task=True,
            default_output_schema="Return the company name, current valuation estimate, most recent funding round details, and list of key investors",
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
