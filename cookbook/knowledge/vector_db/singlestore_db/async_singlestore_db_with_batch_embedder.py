"""
# Run the setup script
```shell
./cookbook/scripts/run_singlestore.sh
```

# Create the database

- Visit http://localhost:8080 and login with `root` and `admin`
- Create the database with your choice of name. Default setup script requires AGNO as database name. `CREATE DATABASE your_database_name;`
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.singlestore import SingleStore
from sqlalchemy.engine import create_engine

USERNAME = getenv("SINGLESTORE_USERNAME")
PASSWORD = getenv("SINGLESTORE_PASSWORD")
HOST = getenv("SINGLESTORE_HOST")
PORT = getenv("SINGLESTORE_PORT")
DATABASE = getenv("SINGLESTORE_DATABASE")
SSL_CERT = getenv("SINGLESTORE_SSL_CERT", None)

db_url = (
    f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"
)
if SSL_CERT:
    db_url += f"&ssl_ca={SSL_CERT}&ssl_verify_cert=true"

db_engine = create_engine(db_url)

vector_db = SingleStore(
    collection="documents",
    db_engine=db_engine,
    schema=DATABASE,
    embedder=OpenAIEmbedder(enable_batch=True),
)
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-mini",
    ),
    knowledge=Knowledge(vector_db=vector_db),
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
