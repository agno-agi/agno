# MySQL Integration

Examples demonstrating MySQL database integration with Agno agents and teams.

## Setup

```shell
pip install mysql-connector-python
```

## Configuration

```python
from agno.agent import Agent
from agno.db.mysql import MySqlDb

db = MySqlDb(db_url="mysql+pymysql://username:password@localhost:3306/database")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`mysql_for_agent.py`](mysql_for_agent.py) - Agent with MySQL storage
- [`mysql_for_team.py`](mysql_for_team.py) - Team with MySQL storage
