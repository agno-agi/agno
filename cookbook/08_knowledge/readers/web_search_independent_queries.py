"""This cookbook shows how to perform multiple independent web searches.

Each search query starts fresh with no state from previous queries.
This allows you to safely reuse a single WebSearchReader instance
for multiple unrelated searches.

Run: `python cookbook/08_knowledge/readers/web_search_independent_queries.py`

Note: Requires SERPAPI_API_KEY or another search API key to be set.
"""

import os

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.web_search_reader import WebSearchReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a single reader instance for multiple searches
reader = WebSearchReader(max_results=5)

print("WebSearchReader for independent queries:")
print(f"  max_results: {reader.max_results}")

# Check if API key is available
if not os.getenv("SERPAPI_API_KEY"):
    print("\nNote: SERPAPI_API_KEY not set. Showing pattern only.")
    print("""
# How to use multiple independent searches:

reader = WebSearchReader(max_results=5)

# Query 1: Python libraries
docs1 = reader.read("Python machine learning libraries 2024")

# Query 2: API design (completely independent)
docs2 = reader.read("Best practices for API design")

# Query 3: Even if URLs overlap with query 1, they're fetched fresh
docs3 = reader.read("Python ML libraries comparison")

# Each query starts with fresh state - no cross-query interference
""")
else:
    print("\nAPI key found! Running searches...")

    knowledge = Knowledge(
        vector_db=PgVector(table_name="web_search_example", db_url=db_url),
    )

    queries = [
        "Python machine learning frameworks",
        "REST API best practices",
    ]

    for query in queries:
        print(f"\nSearching: '{query}'")
        documents = reader.read(query)
        print(f"  Found {len(documents)} documents")
        if documents:
            knowledge.insert(documents=documents)

    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
    )

    print("\nQuerying the knowledge base...")
    agent.print_response(
        "Compare Python ML frameworks and REST API practices",
        markdown=True,
    )
