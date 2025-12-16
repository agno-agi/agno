from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.mongodb import MongoVectorDb

"""
Example connection strings:
"mongodb+srv://<username>:<encoded_password>@cluster0.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"
"""

mdb_connection_string = "mongodb+srv://<username>:<encoded_password>@cluster0.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"

knowledge_base = Knowledge(
    vector_db=MongoVectorDb(
        collection_name="recipes",
        db_url=mdb_connection_string,
        search_index_name="recipes",
        cosmos_compatibility=True,
    ),
)

knowledge_base.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

# Create and use the agent
agent = Agent(knowledge=knowledge_base)

agent.print_response("How to make Thai curry?", markdown=True)
