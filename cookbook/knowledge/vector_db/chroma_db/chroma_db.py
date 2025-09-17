import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from agno.db.postgres.postgres import PostgresDb
from agno.os import AgentOS

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(id="test_db", db_url=db_url)
# Create Knowledge Instance with ChromaDB
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation with ChromaDB",
    vector_db=ChromaDb(
        collection="vectors", path="tmp/chromadb", persistent_client=True
    ),
    contents_db=db,
)

# asyncio.run(
#     knowledge.add_content_async(
#         name="Recipes",
#         url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
#         metadata={"doc_type": "recipe_book"},
#     )
# )

# Create and use the agent
agent = Agent(knowledge=knowledge, db=db)



# agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# # Delete operations examples
# vector_db = knowledge.vector_db
# vector_db.delete_by_name("Recipes")
# # or
# vector_db.delete_by_metadata({"user_tag": "Recipes from website"})


agent_os = AgentOS(
    description="Example app for basic agent with knowledge capabilities",
    os_id="knowledge-demo",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    """ Run your AgentOS:
    Now you can interact with your knowledge base using the API. Examples:
    - http://localhost:8001/knowledge/{id}/documents
    - http://localhost:8001/knowledge/{id}/documents/123
    - http://localhost:8001/knowledge/{id}/documents?agent_id=123
    - http://localhost:8001/knowledge/{id}/documents?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agent_os.serve(app="chroma_db:app", reload=True)