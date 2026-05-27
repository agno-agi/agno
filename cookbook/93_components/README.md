# Agent-as-Config: Persisting Agents, Teams, and Workflows

This cookbook demonstrates how to save and load Agents, Teams, and Workflows to/from a database, enabling configuration-as-code patterns where your AI components can be versioned, shared, and restored.

## Overview

The Agent-as-Config feature allows you to:
- **Save** agents, teams, and workflows to PostgreSQL or SQLite
- **Load** them back with full functionality restored
- **Version** your configurations (each save creates a new version)
- **Delete** configurations (soft or hard delete)
- Use a **Registry** to handle non-serializable components (tools, custom functions, schemas)

## Prerequisites

1. PostgreSQL database running (or SQLite for development)
2. Database URL configured

```bash
# Start PostgreSQL with Docker
./cookbook/scripts/run_pgvector.sh
```

## Cookbooks

| File | Description |
|------|-------------|
| `save_agent.py` | Save an agent configuration to the database |
| `get_agent.py` | Load an agent from the database and run it |
| `save_team.py` | Save a team with member agents to the database |
| `get_team.py` | Load a team and run it with delegation |
| `save_workflow.py` | Save a multi-step workflow to the database |
| `get_workflow.py` | Load a workflow and execute its steps |
| `registry.py` | Use a registry for non-serializable components |

---

## Agents

### Saving an Agent

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    id="my-agent",
    name="My Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
)

# Save to database - returns version number
version = agent.save()
print(f"Saved agent as version {version}")
```

### Loading an Agent

```python
from agno.agent import get_agent_by_id
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Load agent by ID
agent = get_agent_by_id(db=db, id="my-agent")

# Run the agent
agent.print_response("Hello!")
```

### Listing All Agents

```python
from agno.agent import get_agents

agents = get_agents(db=db)
for agent in agents:
    print(f"Agent: {agent.name} (ID: {agent.id})")
```

### Deleting an Agent

```python
# Soft delete (marks as deleted but keeps in database)
agent.delete()

# Hard delete (permanently removes from database)
agent.delete(hard_delete=True)
```

---

## Teams

Teams automatically save their member agents as linked components.

### Saving a Team

```python
from agno.agent import Agent
from agno.team import Team
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Define member agents
researcher = Agent(
    id="researcher-agent",
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Research and gather information",
)

writer = Agent(
    id="writer-agent",
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Write content based on research",
)

# Create and save the team
team = Team(
    id="content-team",
    name="Content Creation Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    description="A team that researches and creates content",
    db=db,
)

version = team.save()
print(f"Saved team as version {version}")
```

### Loading a Team

```python
from agno.team import get_team_by_id

team = get_team_by_id(db=db, id="content-team")

# Run the team - it will delegate to members
team.print_response("Write about AI trends", stream=True)
```

### Listing All Teams

```python
from agno.team import get_teams

teams = get_teams(db=db)
for team in teams:
    print(f"Team: {team.name} (ID: {team.id})")
```

---

## Workflows

Workflows save their steps with links to the agents/teams that execute them.

### Saving a Workflow

```python
from agno.agent import Agent
from agno.workflow import Workflow, Step
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Define agents for each step
research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Extract key insights from data",
)

content_agent = Agent(
    id="content-agent",
    name="Content Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Create content based on research",
)

# Define workflow steps
research_step = Step(name="Research Step", agent=research_agent)
content_step = Step(name="Content Step", agent=content_agent)

# Create and save the workflow
workflow = Workflow(
    id="content-workflow",
    name="Content Creation Workflow",
    description="Research and create content",
    db=db,
    steps=[research_step, content_step],
)

version = workflow.save()
print(f"Saved workflow as version {version}")
```

### Loading a Workflow

```python
from agno.workflow import get_workflow_by_id

workflow = get_workflow_by_id(db=db, id="content-workflow")

# Run the workflow
workflow.print_response(input="AI trends in 2024", markdown=True)
```

### Listing All Workflows

```python
from agno.workflow import get_workflows

workflows = get_workflows(db=db)
for workflow in workflows:
    print(f"Workflow: {workflow.name} (ID: {workflow.id})")
```

---

## Registry for Non-Serializable Components

Some components cannot be serialized to JSON (tools, custom functions, Pydantic schemas). Use a `Registry` to provide these when loading.

### Creating a Registry

```python
from agno.registry import Registry
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.models.openai import OpenAIChat
from pydantic import BaseModel

# Custom tool function
def my_custom_tool(query: str) -> str:
    return f"Results for: {query}"

# Custom schemas
class InputSchema(BaseModel):
    message: str

class OutputSchema(BaseModel):
    result: str
    confidence: float

# Create registry with all non-serializable components
registry = Registry(
    name="My Registry",
    tools=[DuckDuckGoTools(), my_custom_tool],
    models=[OpenAIChat(id="gpt-4o-mini")],
    schemas=[InputSchema, OutputSchema],
)
```

### Loading with a Registry

```python
from agno.agent import get_agent_by_id

# When loading an agent that uses tools or schemas,
# pass the registry to restore non-serializable components
agent = get_agent_by_id(
    db=db,
    id="my-agent",
    registry=registry,
)

# The agent now has its tools and schemas restored
agent.print_response("Search for AI news")
```

### What Gets Restored from Registry

| Component | Serialized | Restored via Registry |
|-----------|------------|----------------------|
| Agent ID, name, description | Yes | - |
| Model configuration | Yes | - |
| Instructions, prompts | Yes | - |
| Tools (Toolkit, Function) | Name only | Full callable |
| Custom functions | Name only | Full callable |
| Pydantic schemas | Name only | Full class |

---

## Database Configuration

### PostgreSQL (Recommended for Production)

```python
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://user:pass@host:port/dbname")
```

### SQLite (Development Only)

```python
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_url="sqlite:///agents.db")
```

---

## Versioning

Each `save()` call creates a new version of the configuration:

```python
# First save - version 1
agent.save()

# Modify and save again - version 2
agent.instructions = ["Updated instructions"]
agent.save()

# Load specific version (coming soon)
# agent = get_agent_by_id(db=db, id="my-agent", version=1)
```

---

## Running the Examples

```bash
# Start PostgreSQL
./cookbook/scripts/run_pgvector.sh

# Run save examples first
python cookbook/93_components/save_agent.py
python cookbook/93_components/save_team.py
python cookbook/93_components/save_workflow.py

# Then run get examples
python cookbook/93_components/get_agent.py
python cookbook/93_components/get_team.py
python cookbook/93_components/get_workflow.py

# Registry example
python cookbook/93_components/registry.py
```
