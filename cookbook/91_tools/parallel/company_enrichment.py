"""
Task API — Company Data Enrichment
==================================

Enrich CRM records or company databases with web intelligence.

USE CASE:
You have a list of company names. You want to add:
- Funding information
- Employee count
- Key executives
- Recent news

The Task API researches each company and returns structured data
that matches your schema.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# COMPANY ENRICHMENT SCHEMA
# =============================================================================
# Define exactly what fields you want for each company.

enrichment_tools = ParallelTools(
    enable_search=False,
    enable_extract=False,
    enable_task=True,
    default_processor="base",
    default_output_schema={
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "website": {"type": "string"},
                "founding_year": {"type": "string"},
                "headquarters": {"type": "string"},
                "employee_count": {"type": "string"},
                "total_funding": {"type": "string"},
                "latest_round": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "amount": {"type": "string"},
                        "date": {"type": "string"},
                    },
                },
                "key_investors": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "executives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "title": {"type": "string"},
                        },
                    },
                },
                "description": {"type": "string"},
            },
            "required": ["company_name"],
        },
    },
)

# =============================================================================
# ENRICHMENT AGENT
# =============================================================================

enrichment_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[enrichment_tools],
    markdown=True,
    instructions="""You enrich company records with web data.
    Use create_task() to research a company, then get_task_result() to retrieve the data.
    Return the structured data for database insertion.""",
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    # Enrich a company record
    enrichment_agent.print_response(
        "Enrich this company record: Anthropic",
        stream=True,
    )
