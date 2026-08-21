"""
Structured output and usage metrics with OpenCode.

Pass a Pydantic model as output_schema and the response content becomes a
validated model instance -- OpenCode enforces the JSON schema server-side.
Every run also reports token usage and cost on RunOutput.metrics.

Requirements:
    npm install -g opencode-ai
    opencode serve --port 4096

Usage:
    .venvs/demo/bin/python cookbook/frameworks/opencode/opencode_structured_output.py
"""

from agno.agents.opencode import OpenCodeAgent
from pydantic import BaseModel


class ProjectSummary(BaseModel):
    name: str
    language: str
    description: str
    file_count: int


agent = OpenCodeAgent(
    name="OpenCode Analyst",
    base_url="http://127.0.0.1:4096",
    output_schema=ProjectSummary,
)

output = agent.run("Analyze the current directory and summarize the project.")

summary = output.content
print("Structured output:")
print("  name:", summary.name)
print("  language:", summary.language)
print("  description:", summary.description)
print("  file_count:", summary.file_count)

if output.metrics is not None:
    print("Usage:")
    print("  total tokens:", output.metrics.total_tokens)
    print("  cost:", output.metrics.cost)
