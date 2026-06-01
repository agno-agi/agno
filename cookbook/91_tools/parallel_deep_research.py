"""
Parallel Deep Research
======================

Task API with all output schema options.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# OUTPUT SCHEMA TYPES
# =============================================================================
# The Task API supports three output schema formats:

# ---------------------------------------------------------------------------
# 1. Auto Schema (default)
# ---------------------------------------------------------------------------
# Parallel automatically determines the best structure for the output.
# Use when you don't need a specific format.

auto_schema_tools = ParallelTools(
    enable_task=True,
    default_output_schema={"type": "auto"},
)

# ---------------------------------------------------------------------------
# 2. JSON Schema
# ---------------------------------------------------------------------------
# Enforce a specific structure using JSON Schema.
# Use when you need predictable, structured data.

json_schema_tools = ParallelTools(
    enable_task=True,
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "valuation": {"type": "string"},
                "funding_rounds": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "round": {"type": "string"},
                            "amount": {"type": "string"},
                            "date": {"type": "string"},
                            "investors": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "required": ["company_name"],
        },
    },
)

# ---------------------------------------------------------------------------
# 3. String Schema
# ---------------------------------------------------------------------------
# Natural language description of expected output.
# Simpler than JSON Schema, good for flexible outputs.

string_schema_tools = ParallelTools(
    enable_task=True,
    default_output_schema="Return the company name, current valuation, each funding round with date and amount, and list of major investors",
)

# =============================================================================
# CREATE AGENTS
# =============================================================================

# Auto schema - flexible output
auto_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[auto_schema_tools],
    markdown=True,
)

# JSON schema - structured output
json_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[json_schema_tools],
    markdown=True,
)

# String schema - guided output
string_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[string_schema_tools],
    markdown=True,
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    # Using JSON schema for structured research
    json_agent.print_response(
        "Research Anthropic's funding history and key investors.",
        stream=True,
    )
