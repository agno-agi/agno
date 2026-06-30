# JSON File Storage Integration

Examples demonstrating JSON file-based storage integration with Agno agents, teams, and workflows.

## Configuration

```python
from agno.db.json import JsonDb

db = JsonDb(db_path="tmp/json_db")
```

## Examples

- [`json_for_agent.py`](json_for_agent.py) - Agent with JSON file storage
- [`json_for_team.py`](json_for_team.py) - Team with JSON file storage
- [`json_for_workflows.py`](json_for_workflows.py) - Workflow with JSON file storage
