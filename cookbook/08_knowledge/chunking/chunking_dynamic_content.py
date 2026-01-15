"""This cookbook shows how to chunk documents created programmatically.

When documents are created from API responses, database queries, or generated
content, they may not have explicit IDs or names. The chunking system generates
unique IDs based on content hash, ensuring database inserts work correctly.

Run: `python cookbook/08_knowledge/chunking/chunking_dynamic_content.py`
"""

from agno.agent import Agent
from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a document WITHOUT id or name (simulates API response)
api_response = Document(
    content="""
    Machine Learning Fundamentals

    Machine learning is a subset of artificial intelligence that enables
    systems to learn and improve from experience. The key concepts include
    supervised learning, unsupervised learning, and reinforcement learning.

    Deep Learning builds on neural networks with multiple layers to learn
    hierarchical representations. Popular architectures include CNNs for
    images and Transformers for text processing.

    Model Training involves feeding data through the network and adjusting
    weights based on the error between predictions and actual values.
    """
)

# Chunk the document - IDs are auto-generated from content hash
chunker = DocumentChunking(chunk_size=300)
chunks = chunker.chunk(api_response)

print("Chunking document without explicit ID:")
print(f"  Original document id: {api_response.id}")
print(f"  Generated {len(chunks)} chunks:")
for i, chunk in enumerate(chunks, 1):
    print(f"    Chunk {i}: {chunk.id}")

# Build a knowledge base from multiple API-style documents
print("\nBuilding knowledge base from dynamic content...")

api_documents = [
    Document(
        content="""
        Python Best Practices: Use virtual environments to isolate dependencies.
        Follow PEP 8 style guidelines. Write docstrings for public functions.
        Use type hints for better code clarity. Handle exceptions appropriately.
        """
    ),
    Document(
        content="""
        Database Design Tips: Normalize data to reduce redundancy. Use indexes
        for frequently queried columns. Consider denormalization for read-heavy
        workloads. Always backup your data. Use transactions for data integrity.
        """
    ),
]

knowledge = Knowledge(
    vector_db=PgVector(table_name="dynamic_content_example", db_url=db_url),
)

for i, doc in enumerate(api_documents, 1):
    chunks = chunker.chunk(doc)
    print(f"  Document {i}: {len(chunks)} chunk(s)")
    for chunk in chunks:
        print(f"    - {chunk.id}")
    # Use vector_db directly to insert pre-chunked documents
    knowledge.vector_db.insert(documents=chunks)

# Create agent and query
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

print("\nQuerying the knowledge base...")
agent.print_response(
    "What are some Python and database best practices?",
    markdown=True,
)
