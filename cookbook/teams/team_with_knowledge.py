from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Setup paths
cwd = Path(__file__).parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)

# Initialize knowledge base
agno_docs_knowledge = Knowledge(
    vector_db=LanceDb(
        uri=str(tmp_dir.joinpath("lancedb")),
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agno_docs_knowledge.add_content(url="https://docs.agno.com/llms-full.txt")

web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=["Always include sources"],
)

team_with_knowledge = Team(
    name="Team with Knowledge",
    members=[web_agent],
    model=OpenAIChat(id="gpt-4o"),
    knowledge=agno_docs_knowledge,
    show_members_responses=True,
    markdown=True,
)

if __name__ == "__main__":
    team_with_knowledge.print_response("Tell me about the Agno framework", stream=True)
