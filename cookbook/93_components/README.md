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
| `auto_populate_registry.py` | Inspect how AgentOS auto-discovers components from teams and workflows |
| `auto_populate_registry_os.py` | Serve an AgentOS and see the auto-discovered components over the API |
| `user_isolation_os.py` | Serve an AgentOS with per-user component isolation |
| `save_prompt.py` | Publish a reusable Prompt and load current and earlier versions |
| `prompt_version_selection.py` | Pin a Prompt version at save time, pin explicitly, or follow latest on load |
| `shared_prompt.py` | Reuse one Prompt across Agents and a Team, with a consumer-owned fallback |

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
    model=OpenAIChat(id="gpt-5.6-luna"),
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
    model=OpenAIChat(id="gpt-5.6-luna"),
    role="Research and gather information",
)

writer = Agent(
    id="writer-agent",
    name="Writer",
    model=OpenAIChat(id="gpt-5.6-luna"),
    role="Write content based on research",
)

# Create and save the team
team = Team(
    id="content-team",
    name="Content Creation Team",
    model=OpenAIChat(id="gpt-5.6-luna"),
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
    model=OpenAIChat(id="gpt-5.6-luna"),
    role="Extract key insights from data",
)

content_agent = Agent(
    id="content-agent",
    name="Content Agent",
    model=OpenAIChat(id="gpt-5.6-luna"),
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
    models=[OpenAIChat(id="gpt-5.6-luna")],
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

## Auto-Populating the Registry

You do not have to declare components twice. When you construct an `AgentOS`, it
recursively walks every agent, team, and workflow you pass in and adds the
**models**, **tools**, **databases**, and **vector databases** they reference to
the registry automatically. This keeps `GET /registry` consistent with what is
actually wired into your OS.

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team

db = SqliteDb(db_file="tmp/auto_registry.db", id="auto-registry-db")

researcher = Agent(id="researcher", model=OpenAIResponses(id="gpt-5.4"), db=db)
writer = Agent(id="writer", model=OpenAIResponses(id="gpt-5.6-luna"))
team = Team(id="content-team", members=[researcher, writer])

# No registry passed; components are discovered from the team members
agent_os = AgentOS(teams=[team])

print([f"{m.provider}:{m.id}" for m in agent_os.registry.models])
# -> ['OpenAI:gpt-5.4', 'OpenAI:gpt-5.6-luna']
```

Details:

- The walk covers nested teams and every workflow step type (including
  `Condition` else-branches and `Router` choices).
- Models include `reasoning_model`, `parser_model`, `output_model`, and fallback
  models. Vector databases and contents databases are pulled from knowledge.
- Deduplication is by id/name, so a model shared across many agents is collected
  once, and components you pass to a `Registry` explicitly are preserved (the
  discovered ones are merged in, never duplicated).
- User objects are only referenced, never mutated.

See `auto_populate_registry.py` (offline inspection) and
`auto_populate_registry_os.py` (served app).

---

## Prompts as Components

A `Prompt` is a reusable block of instructions, a `str` or a `List[str]`, stored
in the component catalogue. Agents and Teams point at it instead of carrying the
text themselves, so one Prompt can serve many components and be updated in one
place.

### Publishing a Prompt

```python
from agno.db.sqlite import SqliteDb
from agno.prompt import Prompt

db = SqliteDb(db_file="tmp/prompts.db", id="prompts-db")

version = Prompt(id="support", content=["Be concise."]).save(db=db)  # publishes version 1
current = Prompt.load("support", db=db)  # current published version
```

- Every explicit `Prompt.save()` publishes a new immutable version, even for
  identical content, and moves the current-version pointer to it.
- Saving an Agent or Team never publishes Prompt content. Publish the Prompt
  first; a component can only be saved against published versions.
- A Prompt cannot be deleted while a saved Agent or Team references it.

### Referencing a Prompt

`instructions` and `system_message` accept a Prompt on both Agent and Team.
`instructions` takes string or list content; `system_message` takes string
content only.

A Prompt in `system_message` completely replaces the generated system message.
For a Team that includes the member roster and delegation instructions. Any
`instructions` behind a custom `system_message` are not used, so they are not
attributed either.

### Choosing a version

```python
Agent(instructions=Prompt(id="support"))                    # pin the current version when the Agent is saved
Agent(instructions=Prompt(id="support", version=3))         # pin version 3
Agent(instructions=Prompt(id="support", version="latest"))  # follow the current version on each load
```

- Omitted is not floating: the pin is resolved once, when the Agent or Team is
  saved, and stored in the saved reference and its link row.
- An integer pins that exact version.
- `version="latest"` resolves the current published version each time the
  component is loaded.
- Resolution happens at load time. An Agent or Team already in memory keeps the
  version it resolved when it was loaded; publishing a new Prompt version
  changes what the next load sees.

### Loading: strict, lenient and fallback

```python
Agent(instructions=Prompt(id="support", version="latest", fallback=["Answer safely."]))
```

- `strict=True` raises when the requested version cannot be resolved.
- Lenient loading (the default) tries the requested version, then the current
  published version, then the component's own inline `fallback` text.
- `fallback` belongs to one Agent or Team relationship and is stored on its
  link row, never in the Prompt. This is Prompt resolution, not model fallback.
- With no usable version and no fallback, loading fails in both modes. A
  Prompt-backed field is never silently dropped, and a component whose Prompt
  is unresolved refuses to run.

### Run attribution

A successful run records which Prompt actually shaped its system message under
the run metadata key `agno_prompt_versions`: one record with `prompt_id`,
`field`, `selection` (`pinned` or `latest`), `requested_version`,
`resolved_version`, `source` (`published` or `inline`), `fallback` and
`fallback_reason`. Prompt text is never copied into metadata. Only the effective
field is recorded, so a custom `system_message` Prompt appears and the
`instructions` it replaces do not.

### Listing views

`get_agents()` and `get_teams()` return listing views. They keep every Prompt
reference and fallback but intentionally do not resolve Prompt text, so a
Prompt-backed field reads `None` there. Load the component normally to get the
text.

### Removing a Prompt from an Agent or Team

- On a normally loaded component, assign `instructions = None` and save: the
  reference and its link row are removed.
- A listing view may already show `instructions is None` because the Prompt
  text was not loaded. Assigning `None` to it again changes nothing, so saving
  it keeps the relationship; a list-then-save cannot delete a Prompt by accident.
- To clear the relationship from a listing object, either load the component
  normally first and then assign `None`, or save
  `component.deep_copy(update={"instructions": None})`.
- Through the components API a config is a whole document: a version written
  without the reference, or with it set to `null`, removes the relationship;
  a `PATCH` without a `config` body leaves it unchanged.

### Out of scope for v1

These are separate follow-ups, not part of this release:

- Structured chat Prompts made of system, user and assistant messages.
- Studio Prompt authoring and management UI. AgentOS and Studio already load
  and run saved Prompt-backed Agents and Teams; the deferred work is the editing
  interface, not runtime reconstruction.
- Workflow Prompt attribution and Workflow-owned run metadata.
- Async Prompt persistence and additional external storage adapters.
- Restore protection for a consumer restored while its Prompt is still archived.
- An optional explicit clearing method such as `clear_prompt()`, if users need it.

### Examples

The three Prompt examples use a local SQLite file, call no model, and can be
re-run; each run publishes further versions.

```bash
python cookbook/93_components/save_prompt.py
python cookbook/93_components/prompt_version_selection.py
python cookbook/93_components/shared_prompt.py
```

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
