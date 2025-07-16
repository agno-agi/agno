"""
# Run the setup script
```shell
./cookbook/scripts/run_singlestore.sh
```

# Create the database

- Visit http://localhost:8080 and login with `root` and `admin`
- Create the database with your choice of name. Default setup script requires AGNO as database name. `CREATE DATABASE your_database_name;`
"""

from os import getenv

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
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

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=SingleStore(
        collection="recipes",
        db_engine=db_engine,
        schema=DATABASE,
    ),
)

# Comment out after first run
knowledge_base.load(recreate=False)

agent = Agent(
    knowledge=knowledge_base,
    # Show tool calls in the response
    show_tool_calls=True,
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)

agent.print_response("How do I make pad thai?", markdown=True)
