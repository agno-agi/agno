"""
This example shows how to customize the compression prompt for domain-specific
use cases. Here we optimize compression for competitive intelligence gathering.

Run: `python cookbook/agents/context_management/tool_call_compression.py`
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Gemini(id="gemini-2.5-pro"),
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
    compress_tool_results=True,
    markdown=True,
    db=SqliteDb(db_file="tmp/dbs/tool_call_compression.db"),
    instructions="Use the search tools and always use the latest information and data.",
    debug_mode=True,  # So we can see the compression manager in action
)

agent.print_response(
    """
    Use the search tools and always for the latest information and data.
    Research recent activities (last 3 months) for these AI companies:
    
    1. OpenAI - product launches, partnerships, pricing
    2. Anthropic - new features, enterprise deals, funding
    3. Google DeepMind - research breakthroughs, product releases
    4. Meta AI - open source releases, research papers
   
    For each, find specific actions with dates and numbers.""",
)
