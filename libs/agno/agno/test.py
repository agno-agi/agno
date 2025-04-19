from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.qdrant import Qdrant
from agno.document import Document

# Collection name
COLLECTION_NAME = "recipes"

# Initialize Qdrant vector database
vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

# Initialize knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    vector_db=vector_db,
)


knowledge_base.load_url(
    url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
    metadata={"user_id": "user_1", "source": "Thai Cookbook"},
    recreate=False,
)

knowledge_base.load_url(
    url="https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
    metadata={"user_id": "user_2", "source": "Cape Cookbook"},
    recreate=False,
)


# Create agent with the knowledge base
agent = Agent(knowledge=knowledge_base, show_tool_calls=True)

print("\nFiltered search example:")
search_results = knowledge_base.search(
    query="How to make Chicken curry, give full steps",
    filters={"meta_data.user_id": "user_2"}
)

print("\n--- Filtered Search Results (User: user_2, Query: 'Chicken curry') ---")
if search_results:
    for i, doc in enumerate(search_results):
        print(f"\n--- Result {i+1} ---")
        print(f"Name: {doc.name}")
        print(f"Metadata: {doc.meta_data}")
        # Print first 500 characters of content
        print(f"Content:\n{doc.content[:5000]}...")
        print("-" * 20)  # Separator
else:
    print("No results found for the specified filter and query.")

# # Standard agent response (no filters in this API yet)
# print("\nStandard agent response:")
# agent.print_response(
#     "List down the ingredients to make Chicken Curry", markdown=True)
