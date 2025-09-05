"""
This example demonstrates how to create a team with knowledge base integration.

The team has access to a knowledge base with Agno documentation and can combine
this knowledge with web search capabilities.
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Setup paths for knowledge storage
cwd = Path(__file__).parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)

# Initialize knowledge base with vector database
agno_docs_knowledge = Knowledge(
    vector_db=LanceDb(
        uri=str(tmp_dir.joinpath("lancedb")),
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Add content to knowledge base
agno_docs_knowledge.add_content(url="https://docs.agno.com/llms-full.txt")

# Create web search agent for supplementary information
web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources"],
)

# Create team with knowledge base integration
team_with_knowledge = Team(
    name="Team with Knowledge",
    members=[web_agent],
    model=OpenAIChat(id="o3-mini"),
    knowledge=agno_docs_knowledge,
    show_members_responses=True,
    markdown=True,
)

if __name__ == "__main__":
    team_with_knowledge.print_response("Tell me about the Agno framework", stream=True)
