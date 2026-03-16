"""
Registry for the Agno demo.

Provides shared tools, models, and database connections for AgentOS.
"""

from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.parallel import ParallelTools
from db import get_postgres_db

demo_db = get_postgres_db()

registry = Registry(
    tools=[ParallelTools()],
    models=[
        OpenAIResponses(id="gpt-5.2"),
        OpenAIResponses(id="gpt-5-mini"),
    ],
    dbs=[demo_db],
)
