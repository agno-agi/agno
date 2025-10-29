# In-Memory Storage

This directory contains examples demonstrating how to use `InMemoryDb` with Agno agents, workflows, and teams.

## Overview

`InMemoryDb` provides a flexible, lightweight storage solution that keeps all session data in memory, with the option to hook it up to any custom persistent storage solution.

Notice this is not recommended for production use cases.

### Highlights

- **No setup or additional dependencies**: No installations or database setup required.
- **Flexible storage**: Use the built-in dictionary or provide your own for custom persistence.

### Important Notes

- **Data Persistence**: Session data is **not persistent** across program restarts unless you provide an external dictionary with your own persistence mechanism.
- **Memory Usage**: All session data is stored in RAM. For applications with many long sessions, monitor memory usage.

## Usage

### Basic Setup

```python
from agno.db.in_memory import InMemoryDb

db = InMemoryDb()
```

### Bring Your Own Dictionary (Flexible Storage Integration)

The real power of InMemoryDb comes from providing your own dictionary for custom storage mechanisms, in case the current first-class supported storage offerings are too opinionated:

```python
from agno.db.in_memory import InMemoryDb
from agno.agent import Agent
from agno.models.openai import OpenAIChat
import json
import boto3

# Example: Save and load sessions to/from S3
def save_sessions_to_s3(sessions_dict, bucket_name, key_name):
    """Save sessions dictionary to S3"""
    s3 = boto3.client('s3')
    s3.put_object(
        Bucket=bucket_name,
        Key=key_name,
        Body=json.dumps(sessions_dict, default=str)
    )

def load_sessions_from_s3(bucket_name, key_name):
    """Load sessions dictionary from S3"""
    s3 = boto3.client('s3')
    try:
        response = s3.get_object(Bucket=bucket_name, Key=key_name)
        return json.loads(response['Body'].read())
    except:
        return {}  # Return empty dict if file doesn't exist

# Step 1: Create agent with external dictionary
my_sessions = {}
db = InMemoryDb(storage_dict=my_sessions)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    add_history_to_context=True,
)

# Run some conversations
agent.print_response("What is the capital of France?")
agent.print_response("What is its population?")

print(f"Sessions in memory: {len(my_sessions)}")

# Step 2: Save sessions to S3
save_sessions_to_s3(my_sessions, "my-bucket", "agent-sessions.json")
print("Sessions saved to S3!")

# Step 3: Later, load sessions from S3 and use with new agent
loaded_sessions = load_sessions_from_s3("my-bucket", "agent-sessions.json")
new_db = InMemoryDb(storage_dict=loaded_sessions)

new_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=new_db,
    session_id=agent.session_id,  # Use same session ID
    add_history_to_context=True,
)

# This agent now has access to the previous conversation
new_agent.print_response("What was my first question?")
```

### Common Operations

```python
# Create storage
db = InMemoryDb()

# Get all sessions
all_sessions = db.get_all_sessions()

# Filter sessions by user
user_sessions = db.get_all_sessions(user_id="user123")

# Get recent sessions
recent = db.get_recent_sessions(limit=5)

# Delete a session
db.delete_session("session_id")

# Clear all sessions
db.drop()
```
