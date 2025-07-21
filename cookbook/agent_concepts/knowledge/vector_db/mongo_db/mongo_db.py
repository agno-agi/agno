import urllib.parse
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.mongodb import MongoDb

# MongoDB connection string examples:
# Local: "mongodb://localhost:27017/"
# Atlas: "mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority"

# Example with MongoDB Atlas (replace with your credentials)
username = "kaus"
password = "agno123"
encoded_password = urllib.parse.quote_plus(password)
connection_string = f"mongodb+srv://{username}:{encoded_password}@agno-mdb.xrv6kn1.mongodb.net/?retryWrites=true&w=majority&appName=agno-mdb"

vector_db = MongoDb(
    collection_name="recipes",
    db_url=connection_string,
    search_index_name="recipes",
)

# Create Knowledge Instance with MongoDB
knowledge = Knowledge(
    name="Basic SDK Knowledge Base", 
    description="Agno 2.0 Knowledge Implementation with MongoDB",
    vector_store=vector_db,
)

knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "Recipes"},
)

# Create and use the agent
agent = Agent(knowledge=knowledge, search_knowledge=True, read_chat_history=True)
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# vector_db.delete_by_name("Recipes")
# # or
# vector_db.delete_by_metadata({"doc_type": "recipe_book"})

# Check final count
print(f"Documents remaining: {vector_db.get_count()}")

