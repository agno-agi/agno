import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.mongodb import MongoVectorDb

mdb_connection_string = (
    "mongodb+srv://mongoadmin:secret@cluster0.mongodb.net/?retryWrites=true&w=majority"
)
mdb_connection_string = "mongodb://mongoadmin:secret@localhost:27017/"
mdb_connection_string = "mongodb+srv://willem_db_user:lpG81MnM8quLg3ZT@cluster0.8mthsqw.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

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
        agent.knowledge.add_content_async(
            path="cookbook/knowledge/testing_resources/cv_1.pdf"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "What can you tell me about the candidate and what are his skills?",
            markdown=True,
        )
    )
