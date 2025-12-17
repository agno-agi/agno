# Team Memory

Persistent memory management for teams to maintain context across interactions.

## Setup

```bash
pip install agno openai pgvector "psycopg[binary]" sqlalchemy
```

Set your API key:
```bash
export OPENAI_API_KEY=xxx
```

### Start PgVector Database

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

## Basic Integration

Teams can maintain persistent memory across sessions:

```python
from agno.team import Team
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

team = Team(
    members=[agent1, agent2],
    db=db,
    enable_user_memories=True,
    session_id="team_session_1",
)
```

## Examples

- **[01_team_with_memory_manager.py](./01_team_with_memory_manager.py)** - Teams with memory management
- **[02_team_with_agentic_memory.py](./02_team_with_agentic_memory.py)** - Agentic memory for teams
