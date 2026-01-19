"""Use AsyncMongoDb as the database for an agent.

Run `pip install openai pymongo motor` to install dependencies

Run a local MongoDB server using:
```bash
docker run -d \
  --name local-mongo \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=mongoadmin \
  -e MONGO_INITDB_ROOT_PASSWORD=secret \
  mongo
```
or use our script:
```bash
./scripts/run_mongodb.sh
```
"""

import asyncio

from agno.agent import Agent
from agno.db.mongo import AsyncMongoDb
from agno.tools.duckduckgo import DuckDuckGoTools

# MongoDB connection settings
db_url = "mongodb://mongoadmin:secret@localhost:27017"

db = AsyncMongoDb(db_url=db_url)

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)

asyncio.run(agent.aprint_response("How many people live in Canada?"))
asyncio.run(agent.aprint_response("What is their national anthem called?"))
