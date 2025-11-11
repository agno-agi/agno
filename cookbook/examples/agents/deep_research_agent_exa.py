"""Example: Advanced Research Agent using Exa Research Tools

This example demonstrates how to use the Exa research tool for complex,
structured research tasks with automatic citation tracking.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ExaTools(enable_research=True, research_model="exa-research-pro")],
    instructions=dedent("""
        You are an expert research analyst with access to advanced research tools.
        
        When you are given a schema to use, pass it to the research tool as output_schema parameter to research tool. 

        The research tool has two parameters:
        - instructions (str): The research topic/question 
        - output_schema (dict, optional): A JSON schema for structured output

        Example: If user says "Research X. Use this schema {'type': 'object', ...}", you must call research tool with the schema.

        If no schema is provided, the tool will auto-infer an appropriate schema.

        Present the findings exactly as provided by the research tool.
    """),
)

# Example 1: Basic research with simple string
agent.print_response(
    "Perform a comprehensive research on the current flagship GPUs from NVIDIA, AMD and Intel. Return a table of model name, MSRP USD, TDP watts, and launch date. Include citations for each cell."
)

# Define a JSON schema for structured research output
# research_schema = {
#     "type": "object",
#     "properties": {
#         "major_players": {
#             "type": "array",
#             "items": {
#                 "type": "object",
#                 "properties": {
#                     "name": {"type": "string"},
#                     "role": {"type": "string"},
#                     "contributions": {"type": "string"},
#                 },
#             },
#         },
#     },
#     "required": ["major_players"],
# }

# agent.print_response(
#     f"Research the top 3 Semiconductor companies in 2024. Use this schema {research_schema}."
# )
