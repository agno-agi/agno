from os import getenv

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lightrag import LightRag

vector_db = LightRag()

vector_db._insert_text("Hello, world!")

# knowledge = Knowledge(
#     name="My Pinecone Knowledge Base",
#     description="This is a knowledge base that uses a Pinecone Vector DB",
#     vector_db=vector_db,
# )

# knowledge.add_content(
#     name="Recipes",
#     url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
#     metadata={"doc_type": "recipe_book"},
# )

# agent = Agent(
#     knowledge=knowledge,
#     search_knowledge=True,
#     read_chat_history=True,
# )

# agent.print_response("How do I make pad thai?", markdown=True)

# vector_db.delete_by_name("Recipes")
# # or
# vector_db.delete_by_metadata({"doc_type": "recipe_book"})
