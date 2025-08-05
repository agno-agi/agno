from os import getenv
import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lightrag import LightRag

vector_db = LightRag(
    api_key=getenv("LIGHTRAG_API_KEY"),
)

# vector_db._insert_text("Hello, world!")



# knowledge = Knowledge(
#     name="My Pinecone Knowledge Base",
#     description="This is a knowledge base that uses a Pinecone Vector DB",
#     vector_db=vector_db,
# )


# knowledge.add_content(
#     name="Recipes",
#     path="cookbook_v2/knowledge/data/filters/cv_1.pdf",
#     metadata={"doc_type": "recipe_book"},
# )

result = asyncio.run(vector_db._insert_text("This is my source", "Hello, world!"))
print(result)

# agent = Agent(
#     knowledge=knowledge,
#     search_knowledge=True,
#     read_chat_history=True,
# )

# agent.print_response("How do I make pad thai?", markdown=True)

# vector_db.delete_by_name("Recipes")
# # or
# vector_db.delete_by_metadata({"doc_type": "recipe_book"})
