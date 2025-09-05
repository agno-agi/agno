# Team State Management

Team state management for maintaining shared state across team members and interactions.

## Setup

```bash
pip install agno openai sqlalchemy
```

Set your API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams can maintain shared state that persists across interactions:

```python
from agno.team import Team
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="team_state.db")

team = Team(
    members=[agent1, agent2],
    db=db,
    enable_agentic_state=True,
    session_state={"shared_data": {}},
)

# State is shared across all team members
team.print_response("Add item to our shared list")
```

## Examples

- **[team_with_nested_shared_state.py](./team_with_nested_shared_state.py)** - Nested teams with shared state management
- **[agentic_session_state.py](./agentic_session_state.py)** - Agentic session state management
- **[session_state_in_instructions.py](./session_state_in_instructions.py)** - Using session state in instructions
