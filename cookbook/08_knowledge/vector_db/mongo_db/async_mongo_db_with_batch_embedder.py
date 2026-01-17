import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.mongodb import MongoVectorDb

# MongoDB connection string
# Example connection strings:
# "mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority"
# "mongodb://localhost:27017/agno?authSource=admin"
mdb_connection_string = "mongodb+srv://<username>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority"

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-mini",
    ),
    knowledge=Knowledge(
        vector_db=MongoVectorDb(
            collection_name="documents",
            db_url=mdb_connection_string,
            database="agno",
            embedder=OpenAIEmbedder(enable_batch=True),
        ),
    ),
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        agent.knowledge.ainsert(path="cookbook/08_knowledge/testing_resources/cv_1.pdf")
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "What can you tell me about the candidate and what are his skills?",
            markdown=True,
        )
    )
