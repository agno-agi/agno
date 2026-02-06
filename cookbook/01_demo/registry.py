"""
Registry for the Agno demo.

Provides shared tools, models, and database connections for AgentOS.
"""

from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from db import get_postgres_db

demo_db = get_postgres_db()

registry = Registry(
    tools=[
        DuckDuckGoTools(),
        CalculatorTools(),
    ],
    models=[
        OpenAIResponses(id="gpt-5.2"),
        OpenAIChat(id="gpt-5-mini"),
    ],
    dbs=[demo_db],
)
