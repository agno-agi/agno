# Session Management

Session management for teams across interactions.

## Setup

```bash
pip install agno openai pgvector "psycopg[binary]" sqlalchemy
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=your_api_key
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

- **[00_in_memory_session.py](./00_in_memory_session.py)** - In-memory session management
- **[01_persistent_session.py](./01_persistent_session.py)** - Database-backed sessions
- **[02_persistent_session_history.py](./02_persistent_session_history.py)** - Session history tracking
- **[03_session_summary.py](./03_session_summary.py)** - Automatic session summarization
- **[04_session_summary_references.py](./04_session_summary_references.py)** - Session summaries with references
- **[05_chat_history.py](./05_chat_history.py)** - Chat history management
- **[06_rename_session.py](./06_rename_session.py)** - Session renaming functionality
- **[07_cache_session.py](./07_cache_session.py)** - Session caching for performance
- **[07_in_memory_db.py](./07_in_memory_db.py)** - In-memory database sessions
- **[08_cache_session.py](./08_cache_session.py)** - Advanced session caching
