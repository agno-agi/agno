"""
Task API — Output Schema Types
==============================

The Task API supports 4 output schema formats.
This cookbook demonstrates each type.

Output Schema Types:
1. Auto — Parallel determines structure
2. JSON Schema — Enforce specific fields
3. String — Natural language description
4. Text — Markdown report with citations

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# 1. AUTO SCHEMA
# =============================================================================
# Let Parallel determine the best output structure.
# Good for exploratory research where you don't know the format upfront.
# NOTE: Auto schema requires "pro" processor or higher.

auto_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_processor="pro",  # Auto schema requires pro+
    default_output_schema={"type": "auto"},
)

auto_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[auto_tools],
    markdown=True,
)

# =============================================================================
# 2. JSON SCHEMA
# =============================================================================
# Enforce specific fields with types.
# Best for data enrichment and structured extraction.

json_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "founding_year": {"type": "string"},
                "total_funding": {"type": "string"},
                "valuation": {"type": "string"},
                "key_investors": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["company_name"],
        },
    },
)

json_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[json_tools],
    markdown=True,
)

# =============================================================================
# 3. STRING SCHEMA
# =============================================================================
# Natural language description of expected output.
# Simpler than JSON Schema, more flexible.

string_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_output_schema="Return the company name, founding year, total funding raised, current valuation, and list of major investors",
)

string_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[string_tools],
    markdown=True,
)

# =============================================================================
# 4. TEXT SCHEMA
# =============================================================================
# Markdown report with embedded citations.
# Best for long-form research reports.

text_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_output_schema={"type": "text"},
)

text_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[text_tools],
    markdown=True,
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    # Using JSON schema for structured company data
    json_agent.print_response(
        "Research Anthropic: funding history and key investors.",
        stream=True,
    )
