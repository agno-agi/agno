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

## Examples

- **[01_team_metrics.py](./01_team_metrics.py)** - Comprehensive team metrics collection and analysis
