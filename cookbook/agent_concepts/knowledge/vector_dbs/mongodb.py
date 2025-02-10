# install pymongo - `pip install pymongo`

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.mongodb import MongoDb

# MongoDB Atlas connection string
"""
Example connection strings:
"mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority"
"mongodb://localhost/?directConnection=true"
"""
mdb_connection_string = "mongodb://ai:ai@localhost:27017/ai?authSource=admin"

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=MongoDb(
        collection_name="recipes",
        db_url=mdb_connection_string,
        wait_until_index_ready=60,
        wait_after_insert=300,
    ),
)  # adjust wait_after_insert and wait_until_index_ready to your needs
knowledge_base.load(recreate=True)

# Create and use the agent
agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("How to make Thai curry?", markdown=True)
