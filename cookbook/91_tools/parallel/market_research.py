"""
Task API — Market Research Reports
==================================

Generate comprehensive market research reports.

USE CASE:
- Industry analysis and trends
- Competitive landscape
- Market sizing
- Key players and their positioning

The Task API synthesizes information from multiple sources
into a cohesive report with citations.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# MARKET RESEARCH CONFIGURATION
# =============================================================================
# Use "text" schema for long-form reports with citations.
# Use "pro" processor for deeper analysis.

research_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_processor="base",
    default_output_schema={"type": "text"},
)

# =============================================================================
# RESEARCH AGENT
# =============================================================================

research_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[research_tools],
    markdown=True,
    instructions="""You are a market research analyst.
    Use create_task() to research industries and markets.
    Provide comprehensive analysis with data points and trends.""",
)

# =============================================================================
# STRUCTURED MARKET REPORT
# =============================================================================
# For structured market data, use JSON schema.

structured_research_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_processor="base",
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "industry": {"type": "string"},
                "market_size": {"type": "string"},
                "growth_rate": {"type": "string"},
                "key_trends": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "major_players": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "market_share": {"type": "string"},
                            "positioning": {"type": "string"},
                        },
                    },
                },
                "challenges": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "opportunities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["industry"],
        },
    },
)

structured_research_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[structured_research_tools],
    markdown=True,
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    # Generate a market research report
    research_agent.print_response(
        "Create a market research report on the AI infrastructure industry. "
        "Include market size, key players, trends, and growth projections.",
        stream=True,
    )
