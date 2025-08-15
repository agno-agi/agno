from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector

# Initialize knowledge base
agno_docs_knowledge = Knowledge(
    vector_db=PgVector(
        table_name="agno_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


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
    update_knowledge=True,
)

if __name__ == "__main__":
    team_with_knowledge.print_response(
        "Store the fact that the Agno framework is a framework for building AI agents",
        stream=True,
    )
