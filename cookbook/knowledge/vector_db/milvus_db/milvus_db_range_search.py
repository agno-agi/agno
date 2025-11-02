"""
Example demonstrating how to use radius and range_filter parameters with Milvus vector database.

This example shows how to perform range-based vector searches using the radius and range_filter parameters.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.milvus import Milvus

# Initialize Milvus with a local file database
vector_db = Milvus(
    collection="recipes_range_search",
    uri="tmp/milvus_range.db",
)

# Create knowledge base
knowledge = Knowledge(
    name="My Milvus Range Search Knowledge Base",
    description="This demonstrates range-based search with radius and range_filter parameters",
    vector_db=vector_db,
)

# Add some content to the knowledge base
knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

# Example 1: Regular search without range parameters
print("=" * 80)
print("Example 1: Regular search (no radius/range_filter)")
print("=" * 80)
agent = Agent(knowledge=knowledge)
agent.print_response("How to make Tom Kha Gai", markdown=True)

# Example 2: Search with radius parameter (range search)
# The radius parameter defines the outer boundary for similarity search
# Only results within this similarity radius will be returned
print("\n" + "=" * 80)
print("Example 2: Search with radius parameter (outer boundary)")
print("=" * 80)
agent2 = Agent(knowledge=knowledge)

# Perform a custom search with radius parameter
query = "How to make Thai curry"
embedding = knowledge.vector_db.embedder.get_embedding(query)

# Search with radius parameter
# Results will have similarity scores within the specified radius
results = knowledge.vector_db.search(
    query=query,
    limit=5,
    search_params={
        "radius": 0.8,  # Only return results with similarity >= 0.8
    },
)

print(f"\nFound {len(results)} documents within radius 0.8:")
for i, doc in enumerate(results, 1):
    print(f"\n{i}. {doc.name}")
    print(f"   Content preview: {doc.content[:100]}...")

# Example 3: Search with both radius and range_filter
# range_filter defines the inner boundary (minimum similarity)
# Combined with radius (outer boundary) creates a similarity range
print("\n" + "=" * 80)
print("Example 3: Search with radius and range_filter (similarity range)")
print("=" * 80)

results_with_range = knowledge.vector_db.search(
    query=query,
    limit=5,
    search_params={
        "radius": 0.8,  # Outer boundary (maximum distance)
        "range_filter": 0.5,  # Inner boundary (minimum distance)
    },
)

print(f"\nFound {len(results_with_range)} documents within range [0.5, 0.8]:")
for i, doc in enumerate(results_with_range, 1):
    print(f"\n{i}. {doc.name}")
    print(f"   Content preview: {doc.content[:100]}...")

# Example 4: Async search with range parameters
print("\n" + "=" * 80)
print("Example 4: Async search with range parameters")
print("=" * 80)

import asyncio


async def async_range_search():
    results = await knowledge.vector_db.async_search(
        query="Thai desserts",
        limit=3,
        search_params={
            "radius": 0.9,
            "range_filter": 0.6,
        },
    )

    print(f"\nAsync search found {len(results)} documents:")
    for i, doc in enumerate(results, 1):
        print(f"\n{i}. {doc.name}")
        print(f"   Content preview: {doc.content[:100]}...")


asyncio.run(async_range_search())

# Clean up
print("\n" + "=" * 80)
print("Cleaning up...")
print("=" * 80)
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
print("✓ Cleaned up successfully!")
