"""This cookbook shows how to implement Agentic RAG using LightRAG.
1. Run: `pip install agno anthropic cohere lancedb tantivy sqlalchemy` to install the dependencies
2. Export your ANTHROPIC_API_KEY
3. Run: `python cookbook/agent_concepts/agentic_search/lightrag/agentic_rag_with_lightrag.py` to run the agent
"""

from agno.agent import Agent
from agno.knowledge.light_rag import LightRagKnowledgeBase, LightRagRetriever
from agno.models.anthropic import Claude
import asyncio
from agno.document.reader.markdown_reader import MarkdownReader

# Create a knowledge base, loaded with documents from a URL
knowledge_base = LightRagKnowledgeBase(
    # urls=["https://docs.agno.com/introduction/agents.md"],
    lightrag_server_url="http://localhost:9621",
    # path="tmp/",
     urls=["https://docs.agno.com/introduction/agents.md"],
     reader=MarkdownReader()
    
)

# asyncio.run(knowledge_base.load())
# asyncio.run(knowledge_base.aload_document(path="tmp/Sellers Declaration.pdf"))
asyncio.run(knowledge_base.aload_document(path="https://docs.agno.com/teams/run.md"))


agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    knowledge=knowledge_base,
    retriever=LightRagRetriever().retriever,
    # search_knowledge=True gives the Agent the ability to search on demand
    # search_knowledge is True by default
    search_knowledge=True,
    instructions=[
        "Include sources in your response.",
        "Always search your knowledge before answering the question.",
        "Use the async_search method to search the knowledge base.",
    ],
    markdown=True)


asyncio.run(agent.aprint_response("How does Agno Team RunResponse look like?"))
