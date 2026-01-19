# MySQL Integration

Examples demonstrating MySQL database integration with Agno agents, teams, and workflows.

## Setup

### Synchronous MySQL

```shell
pip install mysql-connector-python sqlalchemy pymysql
```

### Asynchronous MySQL

```shell
pip install sqlalchemy asyncmy
```

## Configuration

### Synchronous MySQL

```python
from agno.agent import Agent
from agno.db.mysql import MySQLDb

db = MySQLDb(db_url="mysql+pymysql://username:password@localhost:3306/database")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

### Asynchronous MySQL

```python
import asyncio
from agno.agent import Agent
from agno.db.mysql import AsyncMySQLDb

db = AsyncMySQLDb(db_url="mysql+asyncmy://username:password@localhost:3306/database")

agent = Agent(
    db=db,
    add_history_to_context=True,
)

asyncio.run(agent.aprint_response("Hello!"))
```

## Synchronous Examples

- [`mysql_for_agent.py`](mysql_for_agent.py) - Agent with MySQL storage
- [`mysql_for_team.py`](mysql_for_team.py) - Team with MySQL storage

## Asynchronous Examples

- [`async_mysql/async_mysql_for_agent.py`](async_mysql/async_mysql_for_agent.py) - Agent with Async MySQL storage
- [`async_mysql/async_mysql_for_team.py`](async_mysql/async_mysql_for_team.py) - Team with Async MySQL storage
- [`async_mysql/async_mysql_for_workflow.py`](async_mysql/async_mysql_for_workflow.py) - Workflow with Async MySQL storage

## Database URL Format

### Synchronous Drivers

- **PyMySQL**: `mysql+pymysql://user:password@host:port/database`
- **MySQL Connector/Python**: `mysql+mysqlconnector://user:password@host:port/database`

### Asynchronous Drivers

- **asyncmy**: `mysql+asyncmy://user:password@host:port/database`

## Async vs Sync

Choose **AsyncMySQLDb** when:
- Building high-concurrency applications
- Working with async frameworks (FastAPI, Sanic, etc.)
- Need non-blocking database operations

Choose **MySQLDb** when:
- Building traditional synchronous applications
- Simpler deployment requirements
- Working with sync-only libraries
