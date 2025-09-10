# Database Integration

This directory contains examples demonstrating how to integrate various databases with Agno agents, teams, and workflows for persistent storage.

## Setup

```shell
# Install required database drivers based on your choice
pip install psycopg2-binary  # PostgreSQL
pip install pymongo         # MongoDB
pip install mysql-connector-python  # MySQL
pip install redis           # Redis
pip install google-cloud-firestore  # Firestore
pip install boto3           # DynamoDB
pip install singlestoredb   # SingleStore
pip install google-cloud-storage  # GCS
```

Navigate to the specific integration directory for detailed documentation and examples.

## Basic Integration

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://user:password@localhost:5432/dbname")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Supported Databases

- [`postgres`](postgres/) - PostgreSQL relational database integration
- [`sqllite`](sqllite/) - SQLite lightweight database integration
- [`mongo`](mongo/) - MongoDB document database integration
- [`mysql`](mysql/) - MySQL relational database integration
- [`redis`](redis/) - Redis in-memory data structure store integration
- [`singlestore`](singlestore/) - SingleStore distributed SQL database integration
- [`firestore`](firestore/) - Google Cloud Firestore NoSQL database integration
- [`dynamodb`](dynamodb/) - AWS DynamoDB NoSQL database integration
- [`json`](json/) - JSON file-based storage integration
- [`gcs`](gcs/) - Google Cloud Storage JSON blob integration
- [`in_memory`](in_memory/) - In-memory storage with optional persistence hooks

## Session Management

- [`00_in_memory_session_storage.py`](00_in_memory_session_storage.py) - Basic session handling
- [`01_persistent_session_storage.py`](01_persistent_session_storage.py) - Database persistence
- [`02_session_summary.py`](02_session_summary.py) - Session summarization
- [`03_chat_history.py`](03_chat_history.py) - Chat history management
