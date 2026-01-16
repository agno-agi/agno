import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector, SearchType

# ************* Setup Knowledge Databases *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
documents_db = AsyncPostgresDb(
    db_url=db_url,
    id="agno_knowledge_db",
    knowledge_table="agno_knowledge_contents",
)
faq_db = AsyncPostgresDb(
    db_url=db_url,
    id="agno_faq_db",
    knowledge_table="agno_faq_contents",
)
# *******************************

documents_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agno_knowledge_vectors",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=documents_db,
)

faq_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agno_faq_vectors",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=faq_db,
)

# ************* Create Knowledge Agent *************
knowledge_agent = Agent(
    name="Knowledge Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=documents_knowledge,
    search_knowledge=True,
    db=documents_db,
    enable_user_memories=True,
    add_history_to_context=True,
    markdown=True,
    instructions=[
        "You are a helpful assistant with access to Agno documentation.",
        "Search the knowledge base to answer questions about Agno.",
    ],
)
# *******************************

agent_os = AgentOS(
    description="Example app with AgentOS Knowledge (Async)",
    agents=[knowledge_agent],
    knowledge=[faq_knowledge],  # documents_knowledge auto-discovered from agent
)


app = agent_os.get_app()

if __name__ == "__main__":
    asyncio.run(
        documents_knowledge.ainsert(
            name="Agno Docs",
            url="https://docs.agno.com/llms-full.txt",
            skip_if_exists=True,
        )
    )
    asyncio.run(
        faq_knowledge.ainsert(
            name="Agno FAQ",
            text_content=dedent("""
            What is Agno?
            Agno is a framework for building agents.
            Use it to build multi-agent systems with memory, knowledge,
            human in the loop and MCP support.
        """),
            skip_if_exists=True,
        )
    )
    # Run your AgentOS
    # You can test your AgentOS at: http://localhost:7777/
    agent_os.serve(app="agentos_knowledge_async:app", reload=True)
