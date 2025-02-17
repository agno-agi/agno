# Create a knowledge base of PDFs from URLs
from agno.agent.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai.chat import OpenAIChat
from agno.vectordb.lancedb.lance_db import LanceDb
from agno.vectordb.search import SearchType
import pytest



@pytest.fixture(scope="session")
async def loaded_knowledge_base():
    knowledge_base = PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf"],
        vector_db=LanceDb(
            table_name="recipes",
            uri="tmp/lancedb",
            search_type=SearchType.vector,
            embedder=OpenAIEmbedder(),
        ),
    )
    await knowledge_base.aload()
    return knowledge_base

async def test_add_references(loaded_knowledge_base):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=loaded_knowledge_base,
        # Enable RAG by adding references from AgentKnowledge to the user prompt.
        add_references=True,
        # Set as False because Agents default to `search_knowledge=True`
        search_knowledge=False,
        show_tool_calls=True,
        markdown=True,
    )
    response = await agent.arun(
        "How do I make chicken and galangal in coconut milk soup", stream=True
    )
    assert response is not None
    assert len(response) > 0
