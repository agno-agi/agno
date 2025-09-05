"""
1. Create a Redis Cloud Account:
   - Go to https://redis.com/try-free/
   - Sign up for a free Redis Cloud account

2. Create a New Redis Database:
   - Click "Create Database"
   - Choose the FREE tier
   - Select your preferred cloud provider and region
   - Click "Activate"

3. Set Up Database Access:
   - In the database view, go to the "Configuration" or "Security" tab
   - Copy the public endpoint (host and port)
   - Note the default username and password

4. Get Connection String:
   - Redis uses a simple URI format: `redis://<username>:<password>@<host>:<port>`
   - Example: `redis://default:yourpassword@yourhost:yourport`

5. Test Connection:
   - Use a Redis client or library in your code (e.g., `redis` Python package)
   - Ensure the package is installed: `pip install redis`
   - Test with a simple set/get operation

Alternatively, to test locally, you can run a Docker container:

```bash
docker run -d --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```
This will run Redis Stack locally, accessible at `redis://localhost:6379`.
This allows you to test your code without needing a cloud instance.
This also provides a Redis Insights UI at `http://localhost:8001` for managing your Redis database.
"""

from agno.agent import Agent
from agno.knowledge.csv import CSVKnowledgeBase, CSVReader
from agno.vectordb.mongodb import MongoDb
from agno.vectordb.redisvl import RedisVL

from libs.agno.agno.embedder.openai import OpenAIEmbedder

# Redis connection string
"""
Example connection strings:
"redis://default:<password>@<host>:<port>"
"redis://localhost:6379/0"

Replace <password> and <host> with your actual Redis credentials from Redis Cloud or local setup.
"""

"""
This cookbook demonstrates how to use RedisVL as a vector database for a knowledge base in Agno.
The dataset used is: 
https://www.kaggle.com/datasets/quora/question-pairs-dataset.
"""
redis_connection_string = "redis://default:<password>@your-redis-host:6379/0"

knowledge_base = CSVKnowledgeBase(
    path="data/csvs/questions_set.csv",
    reader=CSVReader(chunk_size=50),
    vector_db=RedisVL(
        db_url=redis_connection_string,
        search_index_name="questions_set",
        field_names=["question1", "question_2", "is_duplicate"],
        embedder=OpenAIEmbedder(),
    ),
    num_documents=5,  # Number of documents to return on search
)

# Comment out after first run
knowledge_base.load(recreate=True, upsert=False, skip_existing=False)

# Create and use the agent
query = "I'm a triple Capricorn (Sun, Moon and ascendant in Capricorn) What does that say about me?"
agent = Agent(
    description="An agent that finds if the query is a duplicate of ingested documents or not.",
    instructions=[
        "Is the user query a duplicate to any queries stored in knowledge base? Return True if duplicate, otherwise False."
    ],
    knowledge=knowledge_base,  # previously defined
    search_knowledge=True,
    show_tool_calls=True,
    markdown=True,
)

agent.print_response(query, markdown=True)
