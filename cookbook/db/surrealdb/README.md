# SurrealDB Integration

Examples demonstrating SurrealDB integration with Agno agents, teams, and workflows.

## Setup

```shell
pip install surrealdb
```

## Configuration

```python
credentials = { "username": "root", "password": "root" }
db = SurrealDb(
  None,                   # existing connection
  "ws://localhost:8000",  # url
  credentials,            # credentials
  "agno_ns",              # namespace
  "example_db",           # database
)
```

## Examples

- [`surrealdb_for_agent.py`](surrealdb_for_agent.py) - Agent with SurrealDB storage
- [`surrealdb_for_team.py`](surrealdb_for_team.py) - Team with SurrealDB storage
- [`surrealdb_for_workflow.py`](surrealdb_for_workflow.py) - Workflow with SurrealDB storage
