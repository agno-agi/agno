"""This cookbook shows how to use batch embeddings with OpenAI.

Batch embeddings improve performance by sending multiple texts to the embedding
API in a single request, reducing round-trips and overall latency.

1. Run: `python cookbook/08_knowledge/basic_operations/sync/15_batching.py`
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Configure embedder with batch processing enabled
embedder = OpenAIEmbedder(
    batch_size=100,  # Process embeddings in batches of 100
    dimensions=1536,
    enable_batch=True,  # Required to enable batch embedding API calls
)

vector_db = PgVector(
    table_name="batching_demo",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    embedder=embedder,
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Batching Demo Knowledge Base",
    vector_db=vector_db,
)

# Insert multiple documents to demonstrate batching
# The embedder will batch these together for efficient API calls
knowledge.insert_many(
    [
        {
            "path": "cookbook/08_knowledge/testing_resources/cv_1.pdf",
            "metadata": {
                "user_tag": "Engineering Candidates",
                "candidate": "Jordan Mitchell",
            },
        },
        {
            "url": "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            "metadata": {"user_tag": "Recipes"},
        },
    ]
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("What skills does Jordan Mitchell have?", markdown=True)
