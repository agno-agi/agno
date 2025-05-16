import urllib.parse

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.mongodb import MongoDb

"""
Example connection strings:
"mongodb+srv://<username>:<encoded_password>@cluster0.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"
"""

mdb_connection_string = f"mongodb+srv://<username>:<encoded_password>@cluster0.mongocluster.cosmos.azure.com/?tls=true&authMechanism=SCRAM-SHA-256&retrywrites=false&maxIdleTimeMS=120000"

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=MongoDb(
        collection_name="recipes",
        db_url=mdb_connection_string,
        search_index_name="recipes",
        cosmos_compatibility=True,
    ),
)

# Comment out after first run
knowledge_base.load(recreate=True)

# Create and use the agent
agent = Agent(knowledge=knowledge_base, show_tool_calls=True)

agent.print_response("How to make Thai curry?", markdown=True)
