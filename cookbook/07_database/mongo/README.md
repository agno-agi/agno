# MongoDB Integration

Examples demonstrating MongoDB integration with Agno agents and teams.

## Setup

```shell
pip install pymongo
```

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

## Configuration

```python
from agno.agent import Agent
from agno.db.mongo import MongoDb

db = MongoDb(db_url="mongodb://username:password@localhost:27017")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`mongodb_for_agent.py`](mongodb_for_agent.py) - Agent with MongoDB storage
- [`mongodb_for_team.py`](mongodb_for_team.py) - Team with MongoDB storage
