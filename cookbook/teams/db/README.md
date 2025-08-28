# Database Integration

Database integration and persistence for teams with session storage and chat history.

## Setup

```bash
pip install agno openai pgvector "psycopg[binary]" sqlalchemy
```

Set your API key:
```bash
export OPENAI_API_KEY=xxx
```

### Start PostgreSQL Database

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  --name postgres \
  agnohq/pgvector:16
```

## Basic Integration

Teams can persist sessions and chat history in databases:

```python
from agno.team import Team
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

team = Team(
    members=[agent1, agent2],
    db=db,
    session_id="persistent_session",
)

# Chat history is automatically stored
team.print_response("Hello, team!")
history = team.get_chat_history()
```

## Examples

- **[01_chat_history.py](./01_chat_history.py)** - Persistent chat history storage
- **[02_session_storage.py](./02_session_storage.py)** - Session state persistence
- **[03_user_memories.py](./03_user_memories.py)** - User memory management
- **[04_session_summary.py](./04_session_summary.py)** - Session summarization
- **[05_team_with_storage.py](./05_team_with_storage.py)** - Complete team storage setup
