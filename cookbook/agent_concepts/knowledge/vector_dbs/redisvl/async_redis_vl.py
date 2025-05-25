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

import asyncio

from agno.agent import Agent
from agno.knowledge.csv import CSVKnowledgeBase
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
redis_connection_string = "redis://default:<password>@your-redis-host:6379/0"

knowledge_base = CSVKnowledgeBase(
    path="data/csvs",
    vector_db=RedisVL(
        db_url=redis_connection_string,
        search_index_name="questions_set",
        field_names=["question1", "question_2"],
        embedder=OpenAIEmbedder()
    ),
    num_documents=5,  # Number of documents to return on search
)

# Initialize the Agent with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after the first run
    asyncio.run(knowledge_base.aload(recreate=False))

    asyncio.run(agent.aprint_response("Ask me about something from the knowledge base", markdown=True))


