"""
This example demonstrates using Weaviate as a vector database for semantic search.

Installation:
    pip install weaviate-client

You can use either Weaviate Cloud or a local instance.

Weaviate Cloud Setup:
1. Create account at https://console.weaviate.cloud/
2. Create a cluster and copy the "REST endpoint" and "Admin" API Key. Then set environment variables:
    export WCD_URL="your-cluster-url" 
    export WCD_API_KEY="your-api-key"

Local Development Setup:
1. Install Docker from https://docs.docker.com/get-docker/
2. Run Weaviate locally:
    docker run -d \
        -p 8080:8080 \
        -p 50051:50051 \
        --name weaviate \
        cr.weaviate.io/semitechnologies/weaviate:1.28.4
   or use the script `cookbook/scripts/run_weviate.sh` to start a local instance.
3. Remember to set `local=True` on the Weaviate instantiation.
"""

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Distance, VectorIndex, Weaviate

vector_db = Weaviate(
    collection="recipes",
    search_type=SearchType.hybrid,
    vector_index=VectorIndex.HNSW,
    distance=Distance.COSINE,
    local=True,  # Set to False if using Weaviate Cloud and True if using local instance
)
# Create knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)
knowledge_base.load(recreate=False)  # Comment out after first run

# Create and use the agent
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    show_tool_calls=True,
)
agent.print_response("How to make Thai curry?", markdown=True)
