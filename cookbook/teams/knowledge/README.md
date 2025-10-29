# Team Knowledge

Teams with shared knowledge bases for decision making and responses.

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

Teams can share knowledge bases for enhanced responses:

```python
from agno.team import Team
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="team_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    )
)

team = Team(
    members=[agent1, agent2],
    knowledge=knowledge,
    search_knowledge=True,
)
```

## Examples

- **[01_team_with_knowledge.py](./01_team_with_knowledge.py)** - Teams with shared knowledge bases
- **[02_knowledge_with_agents.py](./02_knowledge_with_agents.py)** - Agent-specific knowledge integration
