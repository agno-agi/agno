# Team Performance Monitoring

Team performance monitoring and metrics collection for analyzing team efficiency.

## Setup

```bash
pip install agno openai pgvector "psycopg[binary]" sqlalchemy
```

Set your OpenAI API key:
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

Teams can collect and analyze performance metrics:

```python
from agno.team import Team
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

team = Team(
    members=[agent1, agent2],
    db=db,
    session_id="metrics_session",
)

# Run team and collect metrics
response = team.run("Analyze market data")
metrics = response.metrics

print(f"Execution time: {metrics.response_time}s")
print(f"Token usage: {metrics.input_tokens} + {metrics.output_tokens}")
```

## Examples

- **[01_team_metrics.py](./01_team_metrics.py)** - Comprehensive team metrics collection and analysis
