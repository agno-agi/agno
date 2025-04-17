import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.docx import DocxKnowledgeBase
from agno.vectordb.lancedb import LanceDb, SearchType

# Create a knowledge base with the DOCX files from the data/docs directory
knowledge_base = DocxKnowledgeBase(
    path=Path("tmp/docs"),
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="docx_reader",
        search_type=SearchType.hybrid,
    ),
)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    asyncio.run(knowledge_base.aload(recreate=False))

    asyncio.run(
        agent.aprint_response(
            "What docs do you have in your knowledge base?", markdown=True
        )
    )
