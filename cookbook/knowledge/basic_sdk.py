from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.agent import Agent
from agno.document.document_v2 import DocumentV2
from agno.models.openai import OpenAIChat


# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base", 
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)

# Add files to the knowledge base
knowledge.add_documents(
    DocumentV2(
        name="CV1",
        paths=["tmp/cv_1.pdf", "tmp/cv_2.pdf"],
        metadata={"user_tag": "Engineering candidates"},
    )
) 


agent = Agent(
    name="My Agent",
    model=OpenAIChat(id="gpt-4o"),
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response("Make a recommendation for a candidate for the role of Software Engineer? Search the knowledge base for the answer.", markdown=True)
