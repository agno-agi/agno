"""
Parallel Task API Options
=========================

Comprehensive examples of all Task API configuration options.

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
# 1. Auto (default) - Parallel infers structure from the task
# 2. JSON Schema - Enforce specific structure with JSON Schema
# 3. String - Natural language description of expected output
# ---------------------------------------------------------------------------

# Example 1: Auto schema (default behavior)
# Parallel automatically determines the best output structure
auto_tools = ParallelTools(
    enable_task=True,
    default_output_schema={"type": "auto"},
)

# Example 2: JSON Schema - strict structure enforcement
# Use when you need specific fields in a known format
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

# Example 3: String schema - natural language description
# Simpler than JSON Schema, good for flexible outputs
string_schema_tools = ParallelTools(
    enable_task=True,
    default_output_schema="Return the company name, current valuation, funding history with dates and amounts, and list of major investors",
)

# ---------------------------------------------------------------------------
# Processor Tiers
# ---------------------------------------------------------------------------
# Processors determine speed, depth, and cost of research:
#
# - "lite"  : Fastest, cheapest, basic research
# - "base"  : Default, good balance of speed and depth
# - "pro"   : Thorough research, higher quality, slower
# ---------------------------------------------------------------------------

# Example 4: Lite processor for quick lookups
lite_tools = ParallelTools(
    enable_task=True,
    default_processor="lite",
)

# Example 5: Base processor (default)
base_tools = ParallelTools(
    enable_task=True,
    default_processor="base",
)

# Example 6: Pro processor for thorough research
pro_tools = ParallelTools(
    enable_task=True,
    default_processor="pro",
)

# ---------------------------------------------------------------------------
# Timeout Configuration
# ---------------------------------------------------------------------------
# Timeout in seconds for waiting on task results (default: 300)
# ---------------------------------------------------------------------------

# Example 7: Short timeout for quick tasks
quick_tools = ParallelTools(
    enable_task=True,
    default_timeout=60,
)

# Example 8: Long timeout for complex research
thorough_tools = ParallelTools(
    enable_task=True,
    default_processor="pro",
    default_timeout=600,
)

# ---------------------------------------------------------------------------
# Combined Configuration
# ---------------------------------------------------------------------------

# Example 9: Full configuration for production use
production_tools = ParallelTools(
    enable_task=True,
    default_processor="pro",
    default_timeout=300,
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "key_findings": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
            "required": ["summary", "key_findings"],
        },
    },
)

# ---------------------------------------------------------------------------
# Create Agents with Different Configurations
# ---------------------------------------------------------------------------

# Quick lookup agent
quick_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[lite_tools],
    instructions="You are a quick fact-checker. Use run_task for simple lookups.",
    markdown=True,
)

# Deep research agent
research_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[production_tools],
    instructions="You are a thorough researcher. Use run_task for comprehensive analysis with citations.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Examples
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Example 1: Quick lookup with lite processor")
    print("-" * 50)
    quick_agent.print_response(
        "What is the current CEO of OpenAI?",
        stream=True,
    )

    print("\n\nExample 2: Deep research with pro processor and JSON schema")
    print("-" * 50)
    research_agent.print_response(
        "Research Anthropic's funding history and key investors.",
        stream=True,
    )
