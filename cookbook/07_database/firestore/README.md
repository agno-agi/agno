# Firestore Integration

Examples demonstrating Google Cloud Firestore integration with Agno agents.

## Setup

```shell
pip install google-cloud-firestore
```

## Configuration

```python
from agno.agent import Agent
from agno.db.firestore import FirestoreDb

db = FirestoreDb(project_id="your-project-id")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Authentication

Set up authentication using one of these methods:

```shell
# Using gcloud CLI
gcloud auth application-default login

# Using environment variable
export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account.json"
```

## Examples

- [`firestore_for_agent.py`](firestore_for_agent.py) - Agent with Firestore storage
