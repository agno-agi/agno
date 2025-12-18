# SingleStore Integration

Examples demonstrating SingleStore database integration with Agno agents and teams.

## Setup

```shell
pip install pymysql sqlalchemy
```

## Configuration

```python
from agno.agent import Agent
from agno.db.singlestore.singlestore import SingleStoreDb

# Using environment variables
USERNAME = getenv("SINGLESTORE_USERNAME")
PASSWORD = getenv("SINGLESTORE_PASSWORD") 
HOST = getenv("SINGLESTORE_HOST")
PORT = getenv("SINGLESTORE_PORT")
DATABASE = getenv("SINGLESTORE_DATABASE")

db_url = f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"

# Or using direct connection string
db_url = "mysql+pymysql://username:password@host:3306/database?charset=utf8mb4"

db = SingleStoreDb(db_url=db_url)

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`singlestore_for_agent.py`](singlestore_for_agent.py) - Agent with SingleStore storage
- [`singlestore_for_team.py`](singlestore_for_team.py) - Team with SingleStore storage
