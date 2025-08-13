import asyncio

from agno.agent import Agent
from agno.knowledge.light_rag import LightRagKnowledgeBase, lightrag_retriever
from agno.models.anthropic import Claude

# Create a knowledge base, loaded with documents from a URL
knowledge_base = LightRagKnowledgeBase(
    lightrag_server_url="http://localhost:9621",
    path="tmp/",  # Load documents from a local directory
    urls=["https://docs.agno.com/introduction/agents.md"],  # Load documents from a URL
)

# Load the knowledge base with the documents from the local directory and the URL
asyncio.run(knowledge_base.load())

# Load the knowledge base with the text
asyncio.run(
    knowledge_base.load_text(text="Dogs and cats are not pets, they are friends.")
)


# Create an agent with the knowledge base and the retriever
agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    knowledge=knowledge_base,
    retriever=lightrag_retriever,
    # search_knowledge=True gives the Agent the ability to search on demand
    # search_knowledge is True by default
    search_knowledge=True,
    instructions=[
        "Include sources in your response.",
        "Always search your knowledge before answering the question.",
        "Use the async_search method to search the knowledge base.",
    ],
    markdown=True,
)


asyncio.run(
    agent.aprint_response(
        "Which candidates are available for the role of a Senior Software Engineer?"
    )
)
asyncio.run(agent.aprint_response("What are Agno Agents?"))
