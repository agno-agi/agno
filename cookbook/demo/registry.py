"""Demo Registry - Tools, models, and databases for AgentOS."""

from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from db import demo_db


def sample_tool():
    return "Hello, world!"


registry = Registry(
    name="Demo Registry",
    tools=[DuckDuckGoTools(), sample_tool, CalculatorTools()],
    models=[
        OpenAIChat(id="gpt-5-mini"),
        OpenAIChat(id="gpt-5"),
        Claude(id="claude-sonnet-4-5"),
    ],
    dbs=[demo_db],
)
