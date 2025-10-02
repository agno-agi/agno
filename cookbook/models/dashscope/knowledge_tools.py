"""
Here is a tool with reasoning capabilities to allow agents to search and analyze information from a knowledge base.

1. Run: `pip install openai agno lancedb tantivy sqlalchemy` to install the dependencies
2. Export your OPENAI_API_KEY
3. Run: `cookbook/models/dashscope/knowledge_tools.py` to run the agent
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.dashscope import DashScope
from agno.tools.knowledge import KnowledgeTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Create a knowledge containing information from a URL
agno_docs = Knowledge(
    # Use LanceDB as the vector database and store embeddings in the `agno_docs` table
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
# Add content to the knowledge
agno_docs.add_content(url="https://docs.agno.com/llms-full.txt")

knowledge_tools = KnowledgeTools(
    knowledge=agno_docs,
    enable_think=True,
    enable_search=True,
    enable_analyze=True,
    add_few_shot=True,
)

agent = Agent(
    model=DashScope(id="qwen-plus"),
    tools=[knowledge_tools],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "How do I build a team of agents in agno?",
        markdown=True,
        stream=True,
    )
