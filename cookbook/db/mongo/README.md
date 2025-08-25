# MongoDB Integration

Examples demonstrating MongoDB integration with Agno agents and teams.

## Setup

```shell
pip install pymongo
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
